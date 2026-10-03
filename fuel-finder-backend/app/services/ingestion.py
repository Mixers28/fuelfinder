"""Data ingestion: fetch from all provider APIs, upsert into local cache."""

import logging
from app.services.fuel_finder_client import fuel_finder_client
from app.database import bulk_upsert_stations, bulk_upsert_prices, get_cache_age_seconds
from app.config import get_settings

logger = logging.getLogger(__name__)


async def refresh_stations():
    """Refresh UK data. German and Dutch areas are fetched when users search."""
    settings = get_settings()

    # UK
    if settings.uk_data_source == "api":
        try:
            stations = await fuel_finder_client.fetch_stations()
            if stations:
                await bulk_upsert_stations(stations)
                logger.info("UK: cached %d stations", len(stations))
            else:
                logger.warning("UK: station fetch returned empty — keeping stale cache")
        except Exception:
            logger.exception("UK: failed to refresh stations")
    else:
        logger.info("UK: skipping API station refresh because UK_DATA_SOURCE=%s", settings.uk_data_source)


async def refresh_prices():
    """Refresh UK prices. Dutch and German prices refresh on demand."""
    settings = get_settings()
    if settings.uk_data_source != "api":
        logger.info("UK: skipping API price refresh because UK_DATA_SOURCE=%s", settings.uk_data_source)
        return

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
