# Fuel Finder

A native iOS app that shows nearby UK and German fuel prices, backed by a FastAPI server using GOV.UK Fuel Finder and Tankerkönig.

![Platform](https://img.shields.io/badge/platform-iOS%2017.6%2B-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI-green)
![Data](https://img.shields.io/badge/data-GOV.UK%20Fuel%20Finder-red)

---

## What it does

- Shows the cheapest nearby petrol and diesel prices using **official government data** (Motor Fuel Price Open Data Regulations 2025)
- Map view with colour-coded price pins — green for cheapest, blue for nearest
- Displays Unleaded Petrol, Super Unleaded, Diesel, and Premium Diesel where available
- German searches fetch prices around the user's location, with a shared area cache and provider rate limiting
- Starts with Nearest and Cheapest options using your location, followed by Postcode search; Nearest is the default and orders stations by straight-line distance. Both list and map results keep the Nearest / Cheapest switch visible above postcode search
- Search towns or postcodes in the UK, Germany and the Netherlands using Apple Maps, without enabling location permission
- Open driving directions in Apple Maps from a station's details
- Save favourite stations on the device; swipe a result or use the star on a station's details
- Remembers the selected fuel between launches
- Savings recommendation on the results list compares the cheapest station with the nearest, using a 40 L fill, 35 imperial mpg and straight-line distances; actual driving routes can cost more. Reports older than 24 hours show a price-age warning instead of a headline savings claim
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
| `TANKERKOENIG_API_KEY` | Tankerkönig key for location-based German price searches |
| `TANKERKOENIG_STALE_TTL` | Maximum German cached-price age during outages (default `3600` seconds) |

Register for API credentials at [developer.fuel-finder.service.gov.uk](https://www.developer.fuel-finder.service.gov.uk)

### Deploy to Railway

1. Connect this repo in Railway, set root directory to `fuel-finder-backend`
2. Add `FUEL_FINDER_CLIENT_ID` and `FUEL_FINDER_CLIENT_SECRET` as environment variables
3. Railway picks up `railway.toml` automatically — no further config needed

---

## iOS App

SwiftUI app targeting iOS 17.6+. Open `fuelfinder/fuelfinder.xcodeproj` in Xcode.

### Point at your backend

Edit the default `baseURL` in `fuelfinder/Services/FuelFinderAPI.swift`:

```swift
init(baseURL: String = "https://your-railway-url.railway.app/api", session: URLSession = .shared)
```

### Key files

| File | Purpose |
|---|---|
| `Services/FuelFinderAPI.swift` | All API calls to the backend |
| `Services/LocationManager.swift` | CoreLocation, while-in-use permission |
| `Services/PlaceSearch.swift` | Apple Maps town/postcode search with country selection and cancellation |
| `Services/UserPreferences.swift` | Device-local fuel choice and favourite station metadata |
| `Models/FuelModels.swift` | Codable structs matching backend responses |
| `Views/ContentView.swift` | Main list view + map/list toggle |
| `Views/StationMapView.swift` | MapKit map with price-bubble pins |
| `Views/StationDetailView.swift` | Per-station detail and all fuel prices |
| `Views/FavouritesView.swift` | Saved stations, favourite actions and Apple Maps directions |
| `Views/SavingsCard.swift` | Savings estimate and a link to the recommended station |

### Checks

Run the `fuelfinder` scheme's tests in Xcode on an iOS 26.5+ simulator. Unit tests cover preference persistence and API request/error handling; the interface test checks search and favourites access and fuel persistence. For the no-permission check, deny location access in the simulator before running it.

Manually check a town and postcode in each supported country, then select a result, open a station, save it and open driving directions. Search and live prices need a network connection. Favourites store metadata only; their detail screen fetches the latest available server prices and shows each price's age. Directions remain available from saved metadata if prices cannot load.

Backend regression tests: `cd fuel-finder-backend && .venv/bin/python -m unittest discover -s tests -v`.

---

## Data source

UK prices are sourced from the [GOV.UK Fuel Finder API](https://www.fuel-finder.service.gov.uk). German prices come from [Tankerkönig](https://creativecommons.tankerkoenig.de/). See the [backend coverage notes](fuel-finder-backend/README.md#german-price-coverage) for caching and provider limits.

---

## Privacy

No account or search/location history is kept. Favourites and fuel choice are stored on the device. Apple Maps resolves town/postcode searches and handles directions. Exact search coordinates are used for nearby results; German provider queries use a shared area centre rounded to roughly a kilometre. Area caches contain station data without user or device identifiers. The privacy manifest declares app-only UserDefaults access using [Apple's CA92.1 reason](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitypereasons). See the [privacy policy](privacy-policy.html).

---

## License

MIT
