# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

UK Fuel Finder MVP — an iOS app backed by a FastAPI caching server that proxies the GOV.UK Fuel Finder API (Motor Fuel Price Open Data Regulations 2025). The backend hides OAuth credentials from the client, caches ~8,300 station records in SQLite, and serves location-based queries to the iOS app.

```
iOS (SwiftUI) → FastAPI backend → GOV.UK Fuel Finder API
                      ↓
                 SQLite cache
```

## Backend (fuel-finder-backend)

**Run the server:**
```bash
cd fuel-finder-backend
cp .env.example .env   # add real credentials first
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive API docs: `http://localhost:8000/docs`

On first start the server fetches all stations and prices, then APScheduler refreshes prices every 15 min and stations every 1 hour.

**Environment variables** (via `.env`):
- `FUEL_FINDER_CLIENT_ID` / `FUEL_FINDER_CLIENT_SECRET` — from developer.fuel-finder.service.gov.uk
- `STATION_CACHE_TTL` (default 3600s) / `PRICE_CACHE_TTL` (default 900s)

**Module layout:**
- `app/config.py` — Pydantic settings, loaded via `get_settings()` (cached with `@lru_cache`)
- `app/database.py` — raw `aiosqlite` functions; no ORM. All writes go through `bulk_upsert_*` for ingestion or `upsert_*` for single-row writes
- `app/services/fuel_finder_client.py` — OAuth client credentials flow + pagination over `/api/v1/pfs` and `/api/v1/pfs/fuel-prices`; normalises divergent API field names
- `app/services/ingestion.py` — `refresh_stations()`, `refresh_prices()`, `refresh_if_stale()` (called at startup)
- `app/services/station_service.py` — Haversine distance in Python, nearby search, `compute_worth_it()` cost-benefit logic
- `app/routers/stations.py` — FastAPI routes under `/api`
- `app/models/schemas.py` — Pydantic response models; fuel types are `E10`, `E5`, `B7`, `SDV`

**Key design constraint:** Distance filtering is done in Python after fetching all stations for a fuel type from SQLite. Acceptable for ≤10k rows; would need PostGIS for horizontal scale.

**`fill-now` recommendation logic** (`station_service.compute_worth_it`): compares tank-fill saving vs extra fuel cost of a round-trip detour, assumes 35 MPG. Baseline is the nearest station; target is the cheapest.

## iOS App (fuel-finder-ios)

SwiftUI app. Open the Xcode project directly — there is no package manager manifest at the top level.

- `Services/FuelFinderAPI.swift` — `baseURL` defaults to `http://localhost:8000/api`; update this when pointing at a deployed backend
- `Services/LocationManager.swift` — CoreLocation, while-in-use only
- `Models/FuelModels.swift` — Swift `Codable` structs mirroring the backend Pydantic schemas
- `Views/ContentView.swift` — main map/list view
- `Views/StationDetailView.swift` — per-station detail

**Info.plist** must include `NSLocationWhenInUseUsageDescription`.

## React MVP (fuel-finder-mvp.jsx)

Single-file React prototype at the repo root — predates the iOS app. Not connected to the backend.

## What's Not Built Yet

Price history (needs a separate `price_history` table to accumulate snapshots), user accounts, price alerts, widgets, route planning.
