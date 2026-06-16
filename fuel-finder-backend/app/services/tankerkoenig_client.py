from __future__ import annotations

"""Tankerkönig client — German fuel prices (creativecommons.tankerkoenig.de).

Registration: https://creativecommons.tankerkoenig.de
Free API key, no cost.
Set TANKERKOENIG_API_KEY in .env to activate.

Fuel type mapping:
  Tankerkönig  → internal
  e10          → E10
  e5           → E5
  diesel       → B7
"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://creativecommons.tankerkoenig.de/json"

_FUEL_MAP = {
    "e10": "E10",
    "e5": "E5",
    "diesel": "B7",
}


async def fetch_stations_de() -> list[dict]:
    """Fetch all German stations from Tankerkönig and return normalised dicts.

    Tankerkönig is location-based (no bulk dump), so we query a grid of
    major cities at a large radius to get broad coverage. For a production
    app, replace with a proper grid-walk or their partner bulk export.
    """
    settings = get_settings()
    if not settings.tankerkoenig_api_key:
        logger.info("TANKERKOENIG_API_KEY not set — skipping Germany")
        return []

    # Representative city centres — radius 50 km each gives ~nationwide coverage
    grid = [
        (52.52,  13.40),  # Berlin
        (48.14,  11.58),  # Munich
        (53.55,   9.99),  # Hamburg
        (51.23,   6.78),  # Düsseldorf
        (50.94,   6.96),  # Cologne
        (50.11,   8.68),  # Frankfurt
        (48.78,   9.18),  # Stuttgart
        (51.34,  12.37),  # Leipzig
        (49.45,  11.08),  # Nuremberg
        (51.51,   7.47),  # Dortmund
    ]

    seen: set[str] = set()
    stations: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for lat, lng in grid:
            try:
                resp = await client.get(
                    f"{BASE_URL}/list.php",
                    params={
                        "lat": lat,
                        "lng": lng,
                        "rad": 50,
                        "sort": "dist",
                        "type": "all",
                        "apikey": settings.tankerkoenig_api_key,
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    logger.warning("Tankerkönig error for (%.2f, %.2f): %s", lat, lng, body.get("message"))
                    continue

                for s in body.get("stations", []):
                    sid = f"de_{s['id']}"
                    if sid in seen:
                        continue
                    seen.add(sid)

                    prices = []
                    for tk_key, fuel_type in _FUEL_MAP.items():
                        val = s.get(tk_key)
                        if isinstance(val, (int, float)) and val > 0:
                            prices.append({
                                "station_id": sid,
                                "fuel_type": fuel_type,
                                # Tankerkönig gives EUR/L — multiply by 100 for euro cents/L
                                "pence_per_litre": round(val * 100, 2),
                                "updated_at": s.get("lastChange", ""),
                            })

                    stations.append({
                        "station_id": sid,
                        "trading_name": s.get("name", "Unknown"),
                        "brand": s.get("brand"),
                        "address": f"{s.get('street', '')} {s.get('houseNumber', '')}".strip(),
                        "postcode": s.get("postCode", ""),
                        "latitude": s["lat"],
                        "longitude": s["lng"],
                        "amenities": [],
                        "opening_hours": None,
                        "country": "de",
                        "prices": prices,
                    })

            except Exception:
                logger.exception("Tankerkönig grid point (%.2f, %.2f) failed", lat, lng)

    logger.info("Tankerkönig: fetched %d German stations", len(stations))
    return stations
