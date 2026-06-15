# UK Fuel Finder MVP 0.1

Find the cheapest fuel near you using official GOV.UK Fuel Finder price data.

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  iOS App     │────▶│  FastAPI Backend  │────▶│  GOV.UK Fuel       │
│  (SwiftUI)   │     │  (cache layer)   │     │  Finder API        │
└──────────────┘     └──────────────────┘     └────────────────────┘
                            │
                     ┌──────┴──────┐
                     │   SQLite    │
                     │   (cache)   │
                     └─────────────┘
```

The backend is a credential-hiding cache. It holds a GOV.UK One Login
with Fuel Finder API client credentials, refreshes station/price data
on a schedule, and serves nearby-station queries to the iOS app.

## Before You Start

### 1. Get API Credentials

1. Go to https://www.developer.fuel-finder.service.gov.uk/public-api
2. Sign in with GOV.UK One Login (create one if needed)
3. Register as an "Information Recipient"
4. Create an application → note your `client_id` and `client_secret`

### 2. Backend Setup

```bash
cd fuel-finder-backend
cp .env.example .env
# Edit .env with your real credentials

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload
```

The server starts on http://localhost:8000. Check http://localhost:8000/docs for the interactive API docs.

On first start, it will:
- Create the SQLite database
- Fetch all ~8,300 stations from Fuel Finder
- Fetch current prices
- Schedule automatic refreshes (stations hourly, prices every 15 min)

### 3. iOS App

Open the FuelFinder Xcode project. Update the `baseURL` in
`Services/FuelFinderAPI.swift` to point at your backend.

Add `NSLocationWhenInUseUsageDescription` to Info.plist:
```
"This app uses your location to find nearby fuel stations. Your location is not stored or tracked."
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stations/nearby` | Find stations near lat/lng for a fuel type |
| GET | `/api/stations/{id}` | Full station detail with all fuel prices |
| GET | `/api/stations/{id}/price-history` | Stub — needs time-series accumulation |
| GET | `/api/recommendation/fill-now` | "Worth the drive?" recommendation |
| GET | `/health` | Cache age and staleness check |

### Example: Nearby Stations

```
GET /api/stations/nearby?lat=57.5075&lng=-1.7843&fuel_type=E10&sort=price&radius=15
```

### Example: Fill Now

```
GET /api/recommendation/fill-now?lat=57.5075&lng=-1.7843&fuel_type=E10&tank_litres=40
```

## What's In / What's Out

### MVP 0.1 (this)
- ✅ Backend caching GOV.UK Fuel Finder data
- ✅ OAuth credential isolation
- ✅ Nearby station search by fuel type
- ✅ Sort by cheapest or nearest
- ✅ Station detail with all fuel prices
- ✅ "Worth the drive?" cost-benefit calculation
- ✅ Last-updated timestamps
- ✅ Privacy-first location (while-in-use only, not stored)

### Not Yet
- ❌ Accounts / login
- ❌ Price alerts
- ❌ Price history (needs accumulation over time)
- ❌ Home screen widgets
- ❌ Route planning
- ❌ Crowdsourced price corrections
- ❌ PostGIS (overkill until scale demands it)

## Data Source

All price data comes from the UK Government Fuel Finder scheme,
established under the Motor Fuel Price (Open Data) Regulations 2025.
Retailers must update prices within 30 minutes of any change.

~8,300 stations participate. Fuel types: E10, E5, B7 (Diesel), SDV (Premium Diesel).

Data quality depends on retailer compliance. The CMA enforces participation.

## Known Limitations

- Price history requires running the backend continuously to accumulate snapshots
- SQLite is single-writer; fine for one backend instance, needs PostgreSQL for horizontal scaling
- Haversine distance is calculated in Python; acceptable for <10k stations per query
- Not all stations report all fuel types
- Some independent stations may report late or inaccurately
