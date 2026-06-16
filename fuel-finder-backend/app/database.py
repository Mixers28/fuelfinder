from __future__ import annotations

"""SQLite database for caching station and price data.

MVP uses SQLite with Haversine distance calculation in Python.
Migrate to PostgreSQL + PostGIS when you need spatial indexing at >10k rows
or concurrent write throughput from multiple ingestion workers.
"""

import aiosqlite
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("DATABASE_PATH", "fuel_finder.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    trading_name TEXT NOT NULL,
    brand TEXT,
    address TEXT NOT NULL,
    postcode TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    amenities TEXT DEFAULT '[]',       -- JSON array
    opening_hours TEXT,
    country TEXT NOT NULL DEFAULT 'uk',
    fetched_at TEXT NOT NULL            -- ISO8601
);

CREATE TABLE IF NOT EXISTS fuel_prices (
    station_id TEXT NOT NULL,
    fuel_type TEXT NOT NULL,            -- E10, E5, B7, SDV
    pence_per_litre REAL NOT NULL,
    updated_at TEXT NOT NULL,           -- ISO8601 from Fuel Finder
    fetched_at TEXT NOT NULL,           -- when we cached it
    PRIMARY KEY (station_id, fuel_type),
    FOREIGN KEY (station_id) REFERENCES stations(station_id)
);

CREATE INDEX IF NOT EXISTS idx_prices_fuel ON fuel_prices(fuel_type);
CREATE INDEX IF NOT EXISTS idx_prices_station ON fuel_prices(station_id);
CREATE INDEX IF NOT EXISTS idx_stations_postcode ON stations(postcode);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
        # Migration: add country column to existing databases
        try:
            await db.execute("ALTER TABLE stations ADD COLUMN country TEXT NOT NULL DEFAULT 'uk'")
            await db.commit()
            logger.info("DB migration: added country column to stations")
        except Exception:
            pass  # Column already exists


async def upsert_station(
    station_id: str,
    trading_name: str,
    brand: str | None,
    address: str,
    postcode: str,
    latitude: float,
    longitude: float,
    amenities: list[str],
    opening_hours: str | None,
):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO stations
               (station_id, trading_name, brand, address, postcode,
                latitude, longitude, amenities, opening_hours, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(station_id) DO UPDATE SET
                 trading_name=excluded.trading_name,
                 brand=excluded.brand,
                 address=excluded.address,
                 postcode=excluded.postcode,
                 latitude=excluded.latitude,
                 longitude=excluded.longitude,
                 amenities=excluded.amenities,
                 opening_hours=excluded.opening_hours,
                 fetched_at=excluded.fetched_at
            """,
            (
                station_id,
                trading_name,
                brand,
                address,
                postcode,
                latitude,
                longitude,
                json.dumps(amenities),
                opening_hours,
                now,
            ),
        )
        await db.commit()


async def upsert_price(
    station_id: str,
    fuel_type: str,
    pence_per_litre: float,
    updated_at: str,
):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO fuel_prices
               (station_id, fuel_type, pence_per_litre, updated_at, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(station_id, fuel_type) DO UPDATE SET
                 pence_per_litre=excluded.pence_per_litre,
                 updated_at=excluded.updated_at,
                 fetched_at=excluded.fetched_at
            """,
            (station_id, fuel_type, pence_per_litre, updated_at, now),
        )
        await db.commit()


async def bulk_upsert_stations(stations: list[dict]):
    """Batch upsert for ingestion efficiency."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """INSERT INTO stations
               (station_id, trading_name, brand, address, postcode,
                latitude, longitude, amenities, opening_hours, country, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(station_id) DO UPDATE SET
                 trading_name=excluded.trading_name,
                 brand=excluded.brand,
                 address=excluded.address,
                 postcode=excluded.postcode,
                 latitude=excluded.latitude,
                 longitude=excluded.longitude,
                 amenities=excluded.amenities,
                 opening_hours=excluded.opening_hours,
                 country=excluded.country,
                 fetched_at=excluded.fetched_at
            """,
            [
                (
                    s["station_id"],
                    s["trading_name"],
                    s.get("brand"),
                    s["address"],
                    s["postcode"],
                    s["latitude"],
                    s["longitude"],
                    json.dumps(s.get("amenities", [])),
                    s.get("opening_hours"),
                    s.get("country", "uk"),
                    now,
                )
                for s in stations
            ],
        )
        await db.commit()


async def bulk_upsert_prices(prices: list[dict]):
    """Batch upsert prices from ingestion."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """INSERT INTO fuel_prices
               (station_id, fuel_type, pence_per_litre, updated_at, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(station_id, fuel_type) DO UPDATE SET
                 pence_per_litre=excluded.pence_per_litre,
                 updated_at=excluded.updated_at,
                 fetched_at=excluded.fetched_at
            """,
            [
                (
                    p["station_id"],
                    p["fuel_type"],
                    p["pence_per_litre"],
                    p["updated_at"],
                    now,
                )
                for p in prices
            ],
        )
        await db.commit()


async def get_station(station_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM stations WHERE station_id = ?", (station_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)


async def get_station_prices(station_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM fuel_prices WHERE station_id = ?", (station_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_stations_with_fuel(fuel_type: str, country: str = "uk") -> list[dict]:
    """Return all stations for a country that have a price for the given fuel type."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT s.*, fp.pence_per_litre, fp.updated_at as price_updated_at
               FROM stations s
               JOIN fuel_prices fp ON s.station_id = fp.station_id
               WHERE fp.fuel_type = ? AND s.country = ?
            """,
            (fuel_type, country),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_cache_age_seconds() -> float | None:
    """How old is the most recent fetched_at in fuel_prices?"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT MAX(fetched_at) FROM fuel_prices"
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        fetched = datetime.fromisoformat(row[0])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - fetched
        return delta.total_seconds()
