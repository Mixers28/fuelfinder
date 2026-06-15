"""UK Fuel Finder MVP — FastAPI backend.

Caches GOV.UK Fuel Finder data locally.
Never exposes Fuel Finder API credentials to the client.

Run: uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import init_db
from app.routers.stations import router as stations_router
from app.services.ingestion import refresh_stations, refresh_prices, refresh_if_stale
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, load initial data, start refresh scheduler."""
    settings = get_settings()
    await init_db()

    # Initial data load (will skip if cache is fresh)
    await refresh_if_stale()

    # Schedule periodic refreshes
    scheduler.add_job(
        refresh_prices,
        "interval",
        seconds=settings.price_cache_ttl,
        id="refresh_prices",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_stations,
        "interval",
        seconds=settings.station_cache_ttl,
        id="refresh_stations",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: prices every %ds, stations every %ds",
        settings.price_cache_ttl,
        settings.station_cache_ttl,
    )

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(
    title="UK Fuel Finder",
    description="Backend cache for GOV.UK Fuel Finder price data",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the iOS app and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(stations_router)


@app.get("/health")
async def health():
    from app.database import get_cache_age_seconds

    age = await get_cache_age_seconds()
    return {
        "status": "ok",
        "cache_age_seconds": round(age, 1) if age else None,
        "cache_stale": age is not None and age > get_settings().price_cache_ttl,
    }
