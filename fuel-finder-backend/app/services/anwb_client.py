from __future__ import annotations

"""ANWB client — Netherlands fuel prices (api.anwb.nl).

The ANWB (Dutch AA) app uses a private REST API with per-station live prices.
To get a working API key, intercept the ANWB iOS app traffic using Proxyman.
Set ANWB_API_KEY in .env / Railway env vars to activate.

API (from reverse engineering):
  Base URL : https://api.anwb.nl/v1
  Stations : GET /fuel/stations?sw={lat},{lng}&ne={lat},{lng}
  Auth     : header  apiKey: <your_key>
  Response : { "items": [ { id, name, brand, address, postalCode,
                             location: { lat, lon },
                             fuelTypes: [ { type, price, updatedAt } ] } ] }

Fuel type mapping:
  Euro95 / euro95  → E10
  Euro98 / euro98  → E5
  Diesel / diesel  → B7
  LPG              → (ignored, not in our schema)
"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.anwb.nl/v1"

# Geobox grid covering the Netherlands (sw_lat, sw_lng, ne_lat, ne_lng)
_NL_GRID = [
    (50.7, 3.3, 52.2, 5.3),  # South — Zeeland, Brabant
    (50.7, 5.3, 52.2, 7.3),  # East  — Limburg, Gelderland
    (52.2, 3.3, 53.6, 5.3),  # North-West — Amsterdam, Den Haag
    (52.2, 5.3, 53.6, 7.3),  # North-East — Overijssel, Groningen
]

_FUEL_MAP = {
    "Euro95": "E10",
    "euro95": "E10",
    "Euro98": "E5",
    "euro98": "E5",
    "Diesel": "B7",
    "diesel": "B7",
}


async def fetch_stations_nl() -> list[dict]:
    """Fetch all Dutch stations from the ANWB API using a geobox grid."""
    settings = get_settings()
    if not settings.anwb_api_key:
        logger.info("ANWB_API_KEY not set — skipping Netherlands")
        return []

    headers = {"apiKey": settings.anwb_api_key}
    seen: set[str] = set()
    stations: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for sw_lat, sw_lng, ne_lat, ne_lng in _NL_GRID:
            try:
                resp = await client.get(
                    f"{BASE_URL}/fuel/stations",
                    params={"sw": f"{sw_lat},{sw_lng}", "ne": f"{ne_lat},{ne_lng}"},
                    headers=headers,
                )
                resp.raise_for_status()
                body = resp.json()

                for s in body.get("items", []):
                    sid = f"nl_{s['id']}"
                    if sid in seen:
                        continue
                    seen.add(sid)

                    loc = s.get("location", {})
                    prices = []
                    for ft in s.get("fuelTypes", []):
                        fuel_type = _FUEL_MAP.get(ft.get("type", ""))
                        price = ft.get("price")
                        if fuel_type and price:
                            prices.append({
                                "station_id": sid,
                                "fuel_type": fuel_type,
                                # ANWB gives EUR/L — multiply by 100 for euro cents/L
                                "pence_per_litre": round(float(price) * 100, 2),
                                "updated_at": ft.get("updatedAt", ""),
                            })

                    stations.append({
                        "station_id": sid,
                        "trading_name": s.get("name", "Unknown"),
                        "brand": s.get("brand"),
                        "address": s.get("address", ""),
                        "postcode": s.get("postalCode", ""),
                        "latitude": loc.get("lat", 0.0),
                        "longitude": loc.get("lon", 0.0),
                        "amenities": [],
                        "opening_hours": None,
                        "country": "nl",
                        "prices": prices,
                    })

            except Exception:
                logger.exception("ANWB grid tile (%.1f,%.1f)→(%.1f,%.1f) failed",
                                 sw_lat, sw_lng, ne_lat, ne_lng)

    logger.info("ANWB: fetched %d Dutch stations", len(stations))
    return stations
