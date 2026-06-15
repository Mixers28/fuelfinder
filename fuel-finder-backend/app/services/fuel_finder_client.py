from __future__ import annotations

"""GOV.UK Fuel Finder API client.

Handles OAuth 2.0 client credentials flow and data ingestion.
Verified against the live API at www.fuel-finder.service.gov.uk:
  - POST /api/v1/oauth/generate_access_token
  - GET  /api/v1/pfs?batch-number=N       (station metadata, 500/batch)
  - GET  /api/v1/pfs/fuel-prices?batch-number=N  (current prices, 500/batch)

All responses are wrapped: {"success": bool, "data": {"data": [...]}}
Pagination stops when the API returns a non-success response (batch exhausted).
"""

import httpx
import logging
from datetime import datetime, timezone, timedelta
from app.config import get_settings

logger = logging.getLogger(__name__)

# Fuel type mapping from API codes to our internal set.
# Live API uses all-caps codes: E10, E5, B7_STANDARD, SDV.
FUEL_TYPE_MAP = {
    "E10": "E10",
    "E5": "E5",
    "B7": "B7",
    "B7_STANDARD": "B7",
    "B7_Standard": "B7",
    "B7_Premium": "B7",
    "B10": "E10",
    "SDV": "SDV",
    "HVO": "SDV",
    "SUPER_DIESEL": "SDV",
}


def _unwrap(body) -> list[dict] | None:
    """Extract the items list from the API response.

    Success shape: bare JSON array
    Failure shape: {"success": false, ...}
    """
    if isinstance(body, list):
        return body or None
    if isinstance(body, dict):
        if body.get("success") is False:
            return None
        # Fallback: nested data
        inner = body.get("data")
        if isinstance(inner, list):
            return inner or None
        if isinstance(inner, dict):
            data = inner.get("data")
            if isinstance(data, list):
                return data or None
    return None


class FuelFinderClient:
    """Async client for the GOV.UK Fuel Finder API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.fuel_finder_base_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    async def _ensure_token(self, client: httpx.AsyncClient):
        """Obtain or refresh the OAuth access token."""
        now = datetime.now(timezone.utc)
        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return

        logger.info("Requesting new Fuel Finder access token")
        resp = await client.post(
            f"{self.base_url}/api/v1/oauth/generate_access_token",
            data={
                "client_id": self.settings.fuel_finder_client_id,
                "client_secret": self.settings.fuel_finder_client_secret,
                "grant_type": "client_credentials",
                "scope": "fuelfinder.read",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()

        token_data = body.get("data", body)
        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3540)
        self._token_expires_at = now + timedelta(seconds=expires_in - 60)
        logger.info("Fuel Finder token acquired, expires in %ds", expires_in)

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def fetch_stations(self) -> list[dict]:
        """Fetch all station metadata via batch pagination. Returns normalised dicts."""
        stations = []
        async with httpx.AsyncClient(timeout=60) as client:
            await self._ensure_token(client)

            batch = 1
            while True:
                resp = await client.get(
                    f"{self.base_url}/api/v1/pfs",
                    headers=self._auth_headers(),
                    params={"batch-number": batch},
                )
                body = resp.json()
                items = _unwrap(body)
                if not items:
                    break

                for raw in items:
                    stations.append(self._normalise_station(raw))

                batch += 1

        logger.info("Fetched %d stations from Fuel Finder", len(stations))
        return stations

    async def fetch_prices(self) -> list[dict]:
        """Fetch all current fuel prices via batch pagination. Returns normalised dicts."""
        prices = []
        async with httpx.AsyncClient(timeout=60) as client:
            await self._ensure_token(client)

            batch = 1
            while True:
                resp = await client.get(
                    f"{self.base_url}/api/v1/pfs/fuel-prices",
                    headers=self._auth_headers(),
                    params={"batch-number": batch},
                )
                body = resp.json()
                items = _unwrap(body)
                if not items:
                    break

                for raw in items:
                    prices.extend(self._normalise_prices(raw))

                batch += 1

        logger.info("Fetched %d price records from Fuel Finder", len(prices))
        return prices

    def _normalise_station(self, raw: dict) -> dict:
        """Map raw API station to our schema.

        Location fields are nested under raw["location"].
        Amenities is already a list of strings.
        """
        loc = raw.get("location", {})
        return {
            "station_id": str(raw.get("node_id", "")),
            "trading_name": raw.get("trading_name", "Unknown"),
            "brand": raw.get("brand_name"),
            "address": loc.get("address_line_1", ""),
            "postcode": loc.get("postcode", ""),
            "latitude": float(loc.get("latitude", 0)),
            "longitude": float(loc.get("longitude", 0)),
            "amenities": raw.get("amenities") or [],
            "opening_hours": None,  # opening_times is complex; omit for MVP
        }

    def _normalise_prices(self, raw: dict) -> list[dict]:
        """Map raw API price record to our schema.

        Each station record contains a fuel_prices array.
        """
        station_id = str(raw.get("node_id", ""))
        results = []

        for entry in raw.get("fuel_prices", []):
            raw_type = entry.get("fuel_type", "")
            normalised_type = FUEL_TYPE_MAP.get(raw_type)
            if not normalised_type:
                continue
            price = entry.get("price")
            if price is None:
                continue
            updated = entry.get("price_last_updated", "")
            results.append({
                "station_id": station_id,
                "fuel_type": normalised_type,
                "pence_per_litre": float(price),
                "updated_at": updated,
            })

        return results


# Singleton
fuel_finder_client = FuelFinderClient()
