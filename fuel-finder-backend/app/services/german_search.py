from __future__ import annotations

"""Shared area snapshots for German searches; no fixed list of cities."""

import asyncio
from dataclasses import dataclass
from time import time

from app.config import get_settings
from app.database import (
    get_german_area,
    store_german_area,
    reserve_provider_request,
    defer_provider_requests,
)
from app.services.geo import KM_PER_MILE, haversine_miles
from app.services.tankerkoenig_client import (
    GermanPricesUnavailable,
    MAX_RADIUS_KM,
    MIN_REQUEST_INTERVAL,
    fetch_stations_de,
)

_refresh_lock: asyncio.Lock | None = None


@dataclass
class GermanArea:
    stations: list[dict]
    radius_miles: float
    notice: str | None = None


def area_coordinates(lat: float, lng: float) -> tuple[str, float, float]:
    # Cache public search areas on a ~1 km grid, without storing the user's exact
    # coordinates or associating areas with a user, device or IP address.
    area_lat, area_lng = round(lat, 2), round(lng, 2)
    return f"{area_lat:.2f},{area_lng:.2f}", area_lat, area_lng


async def get_german_stations(lat: float, lng: float, radius_miles: float) -> GermanArea:
    global _refresh_lock
    settings = get_settings()
    key, area_lat, area_lng = area_coordinates(lat, lng)
    # The entire advertised search circle must fit inside the fetched circle.
    effective_radius = min(
        radius_miles,
        MAX_RADIUS_KM / KM_PER_MILE - haversine_miles(lat, lng, area_lat, area_lng),
    )
    radius_notice = (
        f"German prices are available within {effective_radius:.1f} miles of your location."
        if effective_radius < radius_miles else None
    )
    now = time()
    cached = await get_german_area(key)
    if cached and now - cached["fetched_at"] < settings.price_cache_ttl:
        return GermanArea(cached["stations"], effective_radius, radius_notice)

    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    async with _refresh_lock:
        # Concurrent requests for the same area share the first request's work.
        now = time()
        cached = await get_german_area(key)
        if cached and now - cached["fetched_at"] < settings.price_cache_ttl:
            return GermanArea(cached["stations"], effective_radius, radius_notice)
        try:
            if not settings.tankerkoenig_api_key:
                raise GermanPricesUnavailable("German fuel prices are not available right now.")
            wait = await reserve_provider_request("tankerkoenig", now, MIN_REQUEST_INTERVAL)
            if wait:
                # A local throttle must not push the existing deadline forward.
                raise GermanPricesUnavailable(
                    f"Prices for this area are temporarily unavailable. Please try again in {wait} seconds.",
                    retry_after=wait,
                )
            try:
                stations = await fetch_stations_de(area_lat, area_lng)
            except GermanPricesUnavailable as exc:
                if exc.retry_after:
                    await defer_provider_requests("tankerkoenig", time() + exc.retry_after)
                raise
            await store_german_area(
                key, stations, time(),
                retention_seconds=max(settings.price_cache_ttl, settings.tankerkoenig_stale_ttl),
            )
            return GermanArea(stations, effective_radius, radius_notice)
        except GermanPricesUnavailable:
            if (
                cached
                and time() - cached["fetched_at"] <= settings.tankerkoenig_stale_ttl
                and any(station["prices"] for station in cached["stations"])
            ):
                age_minutes = max(1, int((time() - cached["fetched_at"]) / 60))
                notice = (
                    f"Live German prices are temporarily unavailable. "
                    f"Showing cached prices from {age_minutes} minutes ago."
                )
                if radius_notice:
                    notice += f" {radius_notice}"
                return GermanArea(cached["stations"], effective_radius, notice)
            raise
