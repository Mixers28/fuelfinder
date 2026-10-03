from __future__ import annotations

"""On-demand Dutch prices using the documented Petromap v2 API.

Only complete searches are cached. Three-hour, shared area/fuel snapshots serve
both sorts and recommendations; no scheduled harvesting or permanent NL import.
"""

import asyncio
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import time

import httpx

from app.config import get_settings
from app.database import (
    defer_provider_requests,
    get_petromap_cache,
    reserve_provider_request,
    store_petromap_cache,
)
from app.services.geo import KM_PER_MILE

BASE_URL = "https://api.petromap.eu/v2"
CACHE_SECONDS = 3 * 60 * 60
MAX_RADIUS_METRES = 50_000
GRID_PADDING_METRES = 1_000  # Covers the half-diagonal of a .01-degree NL cell.
MAX_PAGES = 20
STATION_PREFIX = "nl_pm_"
_refresh_lock: asyncio.Lock | None = None
logger = logging.getLogger(__name__)


class DutchPricesUnavailable(Exception):
    def __init__(self, message="Dutch fuel prices are temporarily unavailable. Please try again later.",
                 retry_after=60, provider_backoff=True):
        super().__init__(message)
        self.retry_after = retry_after
        self.provider_backoff = provider_backoff


@dataclass
class DutchArea:
    stations: list[dict]
    radius_miles: float
    notice: str | None = None


def _seconds_until_reset() -> int:
    now = datetime.fromtimestamp(time(), timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((midnight - now).total_seconds()))


async def _get_json(client: httpx.AsyncClient, path: str, params=None, allow_missing=False):
    wait = await reserve_provider_request("petromap", time(), 0)
    if wait:
        # Returning a local cooldown must not extend the provider's deadline.
        raise DutchPricesUnavailable(retry_after=wait, provider_backoff=False)
    response = await client.get(f"{BASE_URL}/{path}", params=params)
    if response.status_code == 404 and allow_missing:
        return None
    if response.is_error:
        logger.warning("Petromap returned HTTP %d", response.status_code)
    if response.status_code in (401, 403):
        raise DutchPricesUnavailable("Dutch fuel prices are not available right now.", 300)
    if response.status_code == 429:
        try:
            body = response.json()
            code = body.get("error") if isinstance(body, dict) else None
        except ValueError:
            code = None
        if code in ("DAILY_BUDGET_EXHAUSTED", "INSUFFICIENT_CREDITS"):
            raise DutchPricesUnavailable(
                "Today's Dutch price allowance has been used. Please try again after midnight UTC.",
                _seconds_until_reset(),
            )
        try:
            wait = max(1, min(86400, int(response.headers.get("Retry-After", "60"))))
        except ValueError:
            wait = 60
        raise DutchPricesUnavailable(retry_after=wait)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or "error" in body:
        raise ValueError("Invalid Petromap response")
    # Usage only: no credentials, coordinates, raw responses or station records.
    charged = response.headers.get("X-Credits-Charged", body.get("credits", 0))
    try:
        logger.info("Petromap: request used %d credits", int(charged))
    except (ValueError, TypeError):
        pass
    return body


async def _cached_load(key: str, loader):
    global _refresh_lock
    cached = await get_petromap_cache(key, time())
    if cached is not None:
        return cached
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    async with _refresh_lock:
        cached = await get_petromap_cache(key, time())
        if cached is not None:
            return cached
        settings = get_settings()
        if not settings.petromap_api_key:
            raise DutchPricesUnavailable("Dutch fuel prices are not available right now.", None)
        # Start retention before retrieval, including paginated requests.
        fetched_at = time()
        try:
            async with httpx.AsyncClient(
                headers={"x-api-key": settings.petromap_api_key}, timeout=20.0,
            ) as client:
                result = await loader(client)
        except DutchPricesUnavailable as exc:
            if exc.retry_after and exc.provider_backoff:
                await defer_provider_requests("petromap", time() + exc.retry_after)
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
            # Never forward an upstream body or exception containing credentials.
            await defer_provider_requests("petromap", time() + 60)
            raise DutchPricesUnavailable() from None
        await store_petromap_cache(key, result, fetched_at + CACHE_SECONDS)
        return result


async def _fuel_tokens(client: httpx.AsyncClient) -> dict[str, str]:
    """Resolve exact grades from the free catalogue, rather than guessing tokens.

    A family search could substitute petrol grades or premium diesel and make
    the comparison misleading. Standard 95 E5 is not Super Unleaded (98 E5).
    """
    cached = await get_petromap_cache("fuels", time())
    if cached is not None:
        return cached
    fetched_at = time()
    body = await _get_json(client, "fuels")
    fuels = body["fuels"]
    if not isinstance(fuels, list) or not fuels:
        raise ValueError("Missing fuel catalogue")
    tokens = {}
    for fuel in sorted(fuels, key=lambda f: f["token"]):
        token = fuel["token"]
        if not isinstance(token, str) or not token:
            raise ValueError("Invalid fuel token")
        if fuel.get("unit") != "L":
            continue
        family, code = fuel.get("family"), fuel.get("en16942")
        premium = fuel.get("grade") == "premium" or fuel.get("additised") is True
        fuel_type = None
        if family == "petrol" and fuel.get("additised") is False:
            if fuel.get("octane") == 95 and code == "E10":
                fuel_type = "E10"
            elif fuel.get("octane") == 98 and code == "E5":
                fuel_type = "E5"
        elif family == "diesel" and code == "B7":
            if premium:
                fuel_type = "SDV"
            elif fuel.get("grade") == "standard" and fuel.get("additised") is False:
                fuel_type = "B7"
        if fuel_type:
            tokens.setdefault(fuel_type, token)
    await store_petromap_cache("fuels", tokens, fetched_at + CACHE_SECONDS)
    return tokens


def _normalise_price(fuel: dict, tokens: dict[str, str]) -> dict | None:
    if not isinstance(fuel, dict) or fuel.get("unit") != "L":
        return None
    fuel_type = next((name for name, token in tokens.items() if token == fuel.get("token")), None)
    price = fuel.get("price")
    if not fuel_type or not isinstance(price, dict) or price.get("currency") != "EUR":
        return None
    amount = price.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 1 <= amount <= 4:
        return None
    try:
        updated = datetime.fromisoformat(price["updatedAt"].replace("Z", "+00:00"))
        if updated.tzinfo is None or updated.timestamp() > time() + 300:
            return None
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None
    return {
        "fuel_type": fuel_type,
        "pence_per_litre": round(amount * 100, 1),
        # Preserve source time, in the whole-second ISO8601 form the app reads.
        "updated_at": updated.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _normalise_place(place: dict, fuels: list, tokens: dict[str, str]) -> dict | None:
    if not isinstance(place, dict):
        raise ValueError("Invalid station")
    if place["kind"] != "fuel" or place["country"] != "NL":
        return None
    public_id = place["id"]
    if not isinstance(public_id, str) or not re.fullmatch(r"NL[A-Za-z0-9_-]{1,78}", public_id):
        raise ValueError("Invalid station ID")
    lat, lng = place["location"]["lat"], place["location"]["lon"]
    if (isinstance(lat, bool) or isinstance(lng, bool)
            or not isinstance(lat, (int, float)) or not isinstance(lng, (int, float))
            or not -90 <= lat <= 90 or not -180 <= lng <= 180):
        raise ValueError("Invalid station coordinates")
    name = place["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Missing station name")
    prices = []
    if place.get("openNow") is not False:
        for fuel in fuels:
            price = _normalise_price(fuel, tokens)
            if price:
                prices.append(price)
    network = place.get("network") or {}
    if not isinstance(network, dict) or not isinstance(place.get("hours") or {}, dict):
        raise ValueError("Invalid station metadata")
    for value in (place.get("street"), place.get("city"), place.get("postalCode"), network.get("name")):
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid station text")
    amenities = place.get("amenities") or []
    if not isinstance(amenities, list) or any(not isinstance(a, str) for a in amenities):
        raise ValueError("Invalid station amenities")
    return {
        "station_id": STATION_PREFIX + public_id,
        "trading_name": name,
        "brand": network.get("name"),
        "address": ", ".join(p for p in (place.get("street"), place.get("city")) if p),
        "postcode": place.get("postalCode") or "",
        "latitude": lat, "longitude": lng, "country": "nl",
        "amenities": ["car_wash" if a == "carwash" else a for a in amenities],
        "opening_hours": "Open 24 hours" if (place.get("hours") or {}).get("alwaysOpen") else None,
        "prices": prices,
    }


async def get_dutch_stations(lat: float, lng: float, radius_miles: float, fuel_type: str) -> DutchArea:
    area_lat, area_lng = round(lat, 2), round(lng, 2)
    effective_radius = min(radius_miles, (MAX_RADIUS_METRES - GRID_PADDING_METRES) / (KM_PER_MILE * 1000))
    radius_metres = min(MAX_RADIUS_METRES, math.ceil(
        (effective_radius * KM_PER_MILE * 1000 + GRID_PADDING_METRES) / 1000,
    ) * 1000)
    key = f"area:{area_lat:.2f},{area_lng:.2f}:{radius_metres}:{fuel_type}"

    async def load(client):
        tokens = await _fuel_tokens(client)
        if fuel_type not in tokens:
            return {"stations": [], "unsupported": True}
        params = {
            "filter": f"circle:{area_lng:.2f},{area_lat:.2f},{radius_metres}",
            "fuel": tokens[fuel_type], "country": "NL", "currency": "EUR",
            "unpriced": "exclude", "sort": "distance",
        }
        stations, cursors = {}, set()
        for _ in range(MAX_PAGES):
            body = await _get_json(client, "places", params)
            if not isinstance(body["places"], list):
                raise ValueError("Invalid station list")
            for place in body["places"]:
                if not isinstance(place, dict):
                    raise ValueError("Invalid station")
                station = _normalise_place(place, [place.get("fuel")], tokens)
                if station:
                    station["prices"] = [p for p in station["prices"] if p["fuel_type"] == fuel_type]
                    stations[station["station_id"]] = station
            cursor = body["nextCursor"]
            if cursor is None:
                return {"stations": list(stations.values()), "unsupported": False}
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Invalid pagination cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        raise DutchPricesUnavailable("This Dutch search covers too many stations. Please try a smaller radius.")

    result = await _cached_load(key, load)
    notice = None
    if result["unsupported"]:
        notice = "Prices for this fuel are not currently available in the Netherlands. Try another fuel."
    elif effective_radius < radius_miles:
        notice = f"Dutch prices are available within {effective_radius:.1f} miles of your location."
    return DutchArea(result["stations"], effective_radius, notice)


async def get_dutch_station(station_id: str) -> dict | None:
    public_id = station_id.removeprefix(STATION_PREFIX)
    if not station_id.startswith(STATION_PREFIX) or not re.fullmatch(r"NL[A-Za-z0-9_-]{1,78}", public_id):
        return None

    async def load(client):
        tokens = await _fuel_tokens(client)
        body = await _get_json(client, f"places/{public_id}", {"currency": "EUR"}, allow_missing=True)
        if body is None:
            return {"missing": True}
        place = body["place"]
        if place["id"] != public_id or not isinstance(place["fuels"], list):
            raise ValueError("Invalid station detail")
        return _normalise_place(place, place["fuels"], tokens) or {"missing": True}

    result = await _cached_load(f"detail:{public_id}", load)
    return None if result.get("missing") else result
