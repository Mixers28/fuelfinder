# Fuel Finder

A native iOS app that shows live UK fuel prices near you, backed by a FastAPI server that caches data from the GOV.UK Fuel Finder API.

![Platform](https://img.shields.io/badge/platform-iOS%2017.6%2B-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)
![Data](https://img.shields.io/badge/data-GOV.UK%20Fuel%20Finder-red)

---

## What it does

- Shows the cheapest nearby petrol and diesel prices using **official government data** (Motor Fuel Price Open Data Regulations 2025)
- Map view with colour-coded price pins — green for cheapest, blue for nearest
- Supports E10, E5 (Super), B7 (Diesel), and SDV (Premium Diesel)
- Sort by price or distance
- "Fill Now" recommendation — calculates whether it's worth driving to the cheapest station vs the nearest based on fuel saved vs extra miles driven
- Prices refresh every hour from the GOV.UK API

---

## Structure

```
fuel-finder-backend/   FastAPI caching server (deploy to Railway / Render)
fuelfinder/            SwiftUI iOS app (Xcode 26)
privacy-policy.html    Privacy policy for App Store submission
```

---

## Backend

Built with FastAPI + SQLite. Caches ~8,300 UK fuel stations and their prices, served via a REST API to the iOS app. Handles OAuth2 authentication with the GOV.UK API so credentials never touch the client.

### Run locally

```bash
cd fuel-finder-backend
cp .env.example .env        # add your GOV.UK API credentials
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`

### Environment variables

| Variable | Description |
|---|---|
| `FUEL_FINDER_CLIENT_ID` | GOV.UK Fuel Finder OAuth client ID |
| `FUEL_FINDER_CLIENT_SECRET` | GOV.UK Fuel Finder OAuth client secret |
| `FUEL_FINDER_BASE_URL` | `https://www.fuel-finder.service.gov.uk` |
| `PRICE_CACHE_TTL` | Seconds between price refreshes (default `3600`) |
| `STATION_CACHE_TTL` | Seconds between station refreshes (default `3600`) |

Register for API credentials at [developer.fuel-finder.service.gov.uk](https://www.developer.fuel-finder.service.gov.uk)

### Deploy to Railway

1. Connect this repo in Railway, set root directory to `fuel-finder-backend`
2. Add `FUEL_FINDER_CLIENT_ID` and `FUEL_FINDER_CLIENT_SECRET` as environment variables
3. Railway picks up `railway.toml` automatically — no further config needed

---

## iOS App

SwiftUI app targeting iOS 17.6+. Open `fuelfinder/fuelfinder.xcodeproj` in Xcode.

### Point at your backend

Edit `fuelfinder/Services/FuelFinderAPI.swift` line 9:

```swift
private let baseURL = "https://your-railway-url.railway.app/api"
```

### Key files

| File | Purpose |
|---|---|
| `Services/FuelFinderAPI.swift` | All API calls to the backend |
| `Services/LocationManager.swift` | CoreLocation, while-in-use permission |
| `Models/FuelModels.swift` | Codable structs matching backend responses |
| `Views/ContentView.swift` | Main list view + map/list toggle |
| `Views/StationMapView.swift` | MapKit map with price-bubble pins |
| `Views/StationDetailView.swift` | Per-station detail and all fuel prices |

---

## Data source

Fuel prices are sourced from the [GOV.UK Fuel Finder API](https://www.fuel-finder.service.gov.uk), published under the Motor Fuel Price Open Data Regulations 2025. Prices are reported directly by fuel retailers — not crowdsourced.

---

## Privacy

No user data is collected or stored. Location is used only to find nearby stations and is discarded immediately after each request. See [privacy policy](privacy-policy.html) for full details.

---

## License

MIT
