"""Data ingestion: fetch from Fuel Finder API, upsert into local cache."""

import logging
from app.services.fuel_finder_client import fuel_finder_client
from app.database import bulk_upsert_stations, bulk_upsert_prices, get_cache_age_seconds
from app.config import get_settings

logger = logging.getLogger(__name__)


async def refresh_stations():
    """Fetch station metadata and cache locally."""
    settings = get_settings()
    try:
        stations = await fuel_finder_client.fetch_stations()
        if stations:
            await bulk_upsert_stations(stations)
            logger.info("Cached %d stations", len(stations))
        else:
            logger.warning("Station fetch returned empty — keeping stale cache")
    except Exception:
        logger.exception("Failed to refresh stations")


async def refresh_prices():
    """Fetch fuel prices and cache locally."""
    try:
        prices = await fuel_finder_client.fetch_prices()
        if prices:
            await bulk_upsert_prices(prices)
            logger.info("Cached %d price records", len(prices))
        else:
            logger.warning("Price fetch returned empty — keeping stale cache")
    except Exception:
        logger.exception("Failed to refresh prices")


async def refresh_if_stale():
    """Check cache age and refresh if past TTL."""
    settings = get_settings()
    age = await get_cache_age_seconds()

    if age is None:
        # No data at all — do full refresh
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
