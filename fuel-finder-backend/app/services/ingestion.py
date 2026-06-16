"""Data ingestion: fetch from all provider APIs, upsert into local cache."""

import logging
from app.services.fuel_finder_client import fuel_finder_client
from app.services.tankerkoenig_client import fetch_stations_de
from app.services.anwb_client import fetch_stations_nl
from app.database import bulk_upsert_stations, bulk_upsert_prices, get_cache_age_seconds
from app.config import get_settings

logger = logging.getLogger(__name__)


async def refresh_stations():
    """Fetch station metadata for all active countries and cache locally."""
    # UK
    try:
        stations = await fuel_finder_client.fetch_stations()
        if stations:
            await bulk_upsert_stations(stations)
            logger.info("UK: cached %d stations", len(stations))
        else:
            logger.warning("UK: station fetch returned empty — keeping stale cache")
    except Exception:
        logger.exception("UK: failed to refresh stations")

    # Germany
    try:
        stations_de = await fetch_stations_de()
        if stations_de:
            await bulk_upsert_stations(stations_de)
            # Prices are bundled with stations from Tankerkönig
            prices_de = [p for s in stations_de for p in s.get("prices", [])]
            if prices_de:
                await bulk_upsert_prices(prices_de)
            logger.info("DE: cached %d stations, %d prices", len(stations_de), len(prices_de))
    except Exception:
        logger.exception("DE: failed to refresh stations")

    # Netherlands
    try:
        stations_nl = await fetch_stations_nl()
        if stations_nl:
            await bulk_upsert_stations(stations_nl)
            prices_nl = [p for s in stations_nl for p in s.get("prices", [])]
            if prices_nl:
                await bulk_upsert_prices(prices_nl)
            logger.info("NL: cached %d stations, %d prices", len(stations_nl), len(prices_nl))
    except Exception:
        logger.exception("NL: failed to refresh stations")


async def refresh_prices():
    """Fetch UK fuel prices and cache locally. DE/NL prices come with stations."""
    try:
        prices = await fuel_finder_client.fetch_prices()
        if prices:
            await bulk_upsert_prices(prices)
            logger.info("UK: cached %d price records", len(prices))
        else:
            logger.warning("UK: price fetch returned empty — keeping stale cache")
    except Exception:
        logger.exception("UK: failed to refresh prices")


async def refresh_if_stale():
    """Check cache age and refresh if past TTL."""
    settings = get_settings()
    age = await get_cache_age_seconds()

    if age is None:
        logger.info("Empty cache — running initial data load")
        await refresh_stations()
        await refresh_prices()
        return

    if age > settings.station_cache_ttl:
        logger.info("Station cache stale (%.0fs old) — refreshing", age)
        await refresh_stations()

    if age > settings.price_cache_ttl:
        logger.info("Price cache stale (%.0fs old) — refreshing", age)
        await refresh_prices()
