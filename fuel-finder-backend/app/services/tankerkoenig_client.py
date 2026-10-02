from __future__ import annotations

"""Location-based German fuel prices from Tankerkönig."""

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.config import get_settings

BASE_URL = "https://creativecommons.tankerkoenig.de/json"
MAX_RADIUS_KM = 25.0
MIN_REQUEST_INTERVAL = 60
_FUEL_MAP = {"e10": "E10", "e5": "E5", "diesel": "B7"}


class GermanPricesUnavailable(Exception):
    """A safe public message, without provider URLs, API keys or response bodies."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after(value: str | None) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        try:
            seconds = math.ceil(
                (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            )
        except (TypeError, ValueError, OverflowError):
            seconds = MIN_REQUEST_INTERVAL
    return max(MIN_REQUEST_INTERVAL, seconds)


def _normalise_station(station: dict, observed_at: str) -> dict:
    station_id = station["id"]
    lat, lng = station["lat"], station["lng"]
    if (
        not isinstance(station_id, str) or not station_id
        or type(lat) not in (int, float) or not -90 <= lat <= 90
        or type(lng) not in (int, float) or not -180 <= lng <= 180
    ):
        raise ValueError("Invalid station identity or coordinates")

    sid = f"de_{station_id}"
    prices = []
    if station.get("isOpen") is not False:
        for key, fuel_type in _FUEL_MAP.items():
            price = station.get(key)
            # The provider uses false for unavailable fuels. Booleans are ints
            # in Python, so deliberately exclude both true and false.
            if type(price) in (int, float) and math.isfinite(price) and price > 0:
                prices.append({
                    "station_id": sid,
                    "fuel_type": fuel_type,
                    "pence_per_litre": round(price * 100, 2),
                    # list.php does not supply a price-change timestamp.
                    "updated_at": observed_at,
                })

    postcode = str(station.get("postCode") or "")
    if postcode.isdigit():
        postcode = postcode.zfill(5)
    return {
        "station_id": sid,
        "trading_name": station.get("name") or "Unknown station",
        "brand": station.get("brand"),
        "address": f"{station.get('street') or ''} {station.get('houseNumber') or ''}".strip(),
        "postcode": postcode,
        "latitude": lat,
        "longitude": lng,
        "amenities": [],
        "opening_hours": None,
        "country": "de",
        "prices": prices,
    }


async def fetch_stations_de(lat: float, lng: float) -> list[dict]:
    """Fetch one 25 km area. The caller owns caching and the shared rate limit."""
    settings = get_settings()
    if not settings.tankerkoenig_api_key:
        raise GermanPricesUnavailable("German fuel prices are not available right now.")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.get(f"{BASE_URL}/list.php", params={
                "lat": lat,
                "lng": lng,
                "rad": MAX_RADIUS_KM,
                "sort": "dist",
                "type": "all",
                "apikey": settings.tankerkoenig_api_key,
            })
        if response.status_code in (429, 503):
            wait = _retry_after(response.headers.get("Retry-After"))
            raise GermanPricesUnavailable(
                f"German prices are temporarily unavailable. Please try again in {wait} seconds.",
                retry_after=wait,
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("ok") is not True or not isinstance(body.get("stations"), list):
            raise ValueError("Invalid provider response")
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        stations = [_normalise_station(station, observed_at) for station in body["stations"]]
        return list({station["station_id"]: station for station in stations}.values())
    except GermanPricesUnavailable:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Never forward exception text: HTTPX exceptions contain the API key URL.
        raise GermanPricesUnavailable(
            "We couldn't refresh German fuel prices. Please try again shortly.",
            retry_after=MIN_REQUEST_INTERVAL,
        ) from None
