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
from asyncio import Lock
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
        self._token_failed_until: datetime | None = None
        self._token_lock = Lock()

    def _base_headers(self) -> dict:
        return {
            "Accept": "application/json",
            "User-Agent": self.settings.fuel_finder_user_agent,
        }

    def _token_payload(self) -> dict:
        return {
            "client_id": self.settings.fuel_finder_client_id,
            "client_secret": self.settings.fuel_finder_client_secret,
            "grant_type": "client_credentials",
            "scope": "fuelfinder.read",
        }

    def _token_headers(self) -> dict:
        return {
            **self._base_headers(),
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _safe_response_headers(self, resp: httpx.Response) -> dict:
        names = (
            "server",
            "date",
            "content-type",
            "content-length",
            "via",
            "x-cache",
            "x-amz-cf-id",
            "x-amz-cf-pop",
            "cf-ray",
        )
        return {name: resp.headers[name] for name in names if name in resp.headers}

    async def _ensure_token(self, client: httpx.AsyncClient):
        """Obtain or refresh the OAuth access token."""
        now = datetime.now(timezone.utc)
        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return
        if self._token_failed_until and now < self._token_failed_until:
            wait = (self._token_failed_until - now).total_seconds()
            raise RuntimeError(f"Fuel Finder token request in backoff for {wait:.0f}s")

        async with self._token_lock:
            now = datetime.now(timezone.utc)
            if self._access_token and self._token_expires_at and now < self._token_expires_at:
                return
            if self._token_failed_until and now < self._token_failed_until:
                wait = (self._token_failed_until - now).total_seconds()
                raise RuntimeError(f"Fuel Finder token request in backoff for {wait:.0f}s")

            logger.info("Requesting new Fuel Finder access token from %s", self.base_url)
            resp = await client.post(
                f"{self.base_url}/api/v1/oauth/generate_access_token",
                data=self._token_payload(),
                headers=self._token_headers(),
            )
            try:
                self._raise_for_status(resp, "Fuel Finder token request")
            except httpx.HTTPStatusError:
                self._token_failed_until = now + timedelta(
                    seconds=self.settings.fuel_finder_auth_backoff_seconds
                )
                raise
            body = resp.json()

            token_data = body.get("data", body)
            self._access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3540)
            self._token_expires_at = now + timedelta(seconds=expires_in - 60)
            self._token_failed_until = None
            logger.info("Fuel Finder token acquired, expires in %ds", expires_in)

    def _auth_headers(self) -> dict:
        return {
            **self._base_headers(),
            "Authorization": f"Bearer {self._access_token}",
        }

    def _raise_for_status(self, resp: httpx.Response, context: str):
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            body = resp.text[:500].replace("\n", " ")
            logger.error(
                "%s failed: status=%d url=%s headers=%s body=%s",
                context,
                resp.status_code,
                resp.request.url,
                self._safe_response_headers(resp),
                body,
            )
            raise

    def _exhausted_batch(self, resp: httpx.Response, context: str) -> bool:
        if resp.status_code not in (400, 404):
            return False
        try:
            body = resp.json()
        except ValueError:
            self._raise_for_status(resp, context)
        if _unwrap(body) is None:
            logger.info("%s exhausted: status=%d", context, resp.status_code)
            return True
        return False

    async def diagnose_token_request(self) -> dict:
        """Run a single redacted OAuth probe from the current runtime."""
        url = f"{self.base_url}/api/v1/oauth/generate_access_token"
        result = {
            "base_url": self.base_url,
            "url": url,
            "client_id_present": bool(self.settings.fuel_finder_client_id),
            "client_secret_present": bool(self.settings.fuel_finder_client_secret),
            "user_agent": self.settings.fuel_finder_user_agent,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.post(
                    url,
                    data=self._token_payload(),
                    headers=self._token_headers(),
                )
            except httpx.RequestError as exc:
                return {
                    **result,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

        body_snippet = resp.text[:500].replace("\n", " ")
        diagnostic = {
            **result,
            "ok": resp.is_success,
            "status_code": resp.status_code,
            "content_type": resp.headers.get("content-type"),
            "headers": self._safe_response_headers(resp),
        }
        if resp.is_success:
            try:
                body = resp.json()
                token_data = body.get("data", body) if isinstance(body, dict) else {}
                diagnostic["token_present"] = bool(token_data.get("access_token"))
                diagnostic["expires_in"] = token_data.get("expires_in")
            except ValueError:
                diagnostic["body_snippet"] = body_snippet
        else:
            diagnostic["body_snippet"] = body_snippet
        return diagnostic

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
                if self._exhausted_batch(resp, f"Fuel Finder stations batch {batch}"):
                    break
                self._raise_for_status(resp, f"Fuel Finder stations batch {batch}")
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
                if self._exhausted_batch(resp, f"Fuel Finder prices batch {batch}"):
                    break
                self._raise_for_status(resp, f"Fuel Finder prices batch {batch}")
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
