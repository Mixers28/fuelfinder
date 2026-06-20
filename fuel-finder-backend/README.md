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

### Temporary CSV Import Mode

If the Fuel Finder API is unavailable from the deployment host, use the
twice-daily email CSV as the UK data source:

```bash
UK_DATA_SOURCE=csv
ADMIN_IMPORT_TOKEN=make-this-a-long-random-value
```

Local import into SQLite:

```bash
cd fuel-finder-backend
.venv/bin/python scripts/import_fuel_finder_csv.py ../UpdatedFuelPrice-1781794800023.csv
```

Deployed import:

```bash
curl -X POST \
  -H "x-admin-token: make-this-a-long-random-value" \
  -H "content-type: text/csv" \
  --data-binary @UpdatedFuelPrice-1781794800023.csv \
  https://your-backend.example.com/admin/import/fuel-finder-csv
```

### Railway Deployment

Use Railway as the backend host while the Fuel Finder OAuth endpoint is blocked
from generic cloud egress.

Railway variables:

```bash
UK_DATA_SOURCE=csv
ADMIN_IMPORT_TOKEN=make-this-a-long-random-value
FUEL_FINDER_BASE_URL=https://www.fuel-finder.service.gov.uk
FUEL_FINDER_USER_AGENT=FuelFinderBackend/0.1
TANKERKOENIG_API_KEY=your_tankerkoenig_key
ANWB_API_KEY=
```

Attach a Railway volume to the backend service. The app automatically stores
SQLite at `$RAILWAY_VOLUME_MOUNT_PATH/fuel_finder.db` when that variable is
provided by Railway. Without a volume, the imported CSV cache can disappear on
redeploy.

Railway import example:

```bash
curl -X POST \
  -H "x-admin-token: make-this-a-long-random-value" \
  -H "content-type: text/csv" \
  --data-binary @UpdatedFuelPrice-1781794800023.csv \
  https://your-railway-domain.up.railway.app/admin/import/fuel-finder-csv
```

### Automated Email CSV Import

The repo includes a Google Apps Script at
`automation/google_apps_script_import_fuel_csv.js`.

Gmail setup:

1. Create a Gmail label named `fuel-finder-csv`.
2. Create a Gmail filter for Fuel Finder CSV emails and apply that label. The
   script also falls back to searching
   `from:fuel.finder@notifications.service.gov.uk subject:"UPDATED FUEL PRICES"`
   if the label is missing.
3. Open https://script.google.com and create a new Apps Script project.
4. Paste in `automation/google_apps_script_import_fuel_csv.js`.
5. Run this once from the Apps Script editor, replacing the values:

```javascript
setFuelFinderImportConfig(
  "https://your-railway-domain.up.railway.app/admin/import/fuel-finder-csv",
  "make-this-a-long-random-value"
)
```

6. Run `installHourlyFuelFinderTrigger()` once.
7. Run `debugFuelFinderImportSearch()` manually once to confirm the script can
   see the email and download URL.
8. Run `importLatestFuelFinderCsv()` manually once to approve permissions and test.

The script searches for the newest unprocessed labelled Fuel Finder email,
downloads the `get-latest-fuel-prices-csv` link or uses an
`UpdatedFuelPrice*.csv` attachment if one exists, posts the CSV to Railway,
then labels the thread `fuel-finder-imported`. Failed imports are labelled
`fuel-finder-import-error`.

If Google Apps Script is blocked from downloading the Fuel Finder CSV directly,
it falls back to sending the download URL to
`/admin/import/fuel-finder-csv-url`, where the backend downloads and imports it.
If both Google and Railway are blocked, use the local Mac importer below.

The backend stores imported CSV SHA256 hashes, so repeated uploads of the same
attachment are treated as already imported instead of replacing the cache again.

### Local Mac CSV Automation

Fuel Finder may block cloud runtimes from downloading the CSV. In that case,
run the download from a trusted local Mac and upload the CSV bytes to Railway:

```bash
cd fuel-finder-backend
ADMIN_IMPORT_TOKEN="your-admin-import-token" \
FUEL_FINDER_IMPORT_URL="https://fuelfinder-production.up.railway.app/admin/import/fuel-finder-csv" \
python3 automation/local_fuel_csv_import.py
```

To automate it with launchd:

```bash
cp automation/com.fuelfinder.csv-import.plist.example ~/Library/LaunchAgents/com.fuelfinder.csv-import.plist
open -e ~/Library/LaunchAgents/com.fuelfinder.csv-import.plist
```

Replace `REPLACE_WITH_A_NEW_RANDOM_ADMIN_IMPORT_TOKEN`, then load it:

```bash
launchctl unload ~/Library/LaunchAgents/com.fuelfinder.csv-import.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.fuelfinder.csv-import.plist
launchctl start com.fuelfinder.csv-import
tail -f /tmp/fuelfinder-csv-import.log
```

The template runs every 6 hours and on load. Use a separate random
`ADMIN_IMPORT_TOKEN`; do not reuse third-party API keys.

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
