from __future__ import annotations

"""Directprijzen client — Netherlands fuel prices (directprijzen.nl).

Registration: https://www.directprijzen.nl/api
Set DIRECTPRIJZEN_API_KEY in .env to activate.

Fuel type mapping (Dutch names):
  euro95 / E10  → E10
  euro98 / SP98 → E5
  diesel        → B7
  lpg           → (not supported in our schema)

TODO: Once you have an API key, fill in the endpoint and field names
below. The skeleton is wired into the ingestion pipeline already.
"""

import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


async def fetch_stations_nl() -> list[dict]:
    """Fetch all Dutch stations from Directprijzen.

    Not yet implemented — add API key and fill in the HTTP calls below.
    Structure should mirror tankerkoenig_client.fetch_stations_de().
    """
    settings = get_settings()
    if not settings.directprijzen_api_key:
        logger.info("DIRECTPRIJZEN_API_KEY not set — skipping Netherlands")
        return []

    # TODO: implement once API credentials are obtained
    # Likely endpoint: https://www.directprijzen.nl/api/v1/stations
    # Params: apikey=...
    # Fields to normalise: id, name, brand, address, postcode, lat, lng,
    #   prices[{fuel_type, price_per_liter, updated_at}]
    logger.warning("Directprijzen client not yet implemented")
    return []
