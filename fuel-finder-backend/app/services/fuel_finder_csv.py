from __future__ import annotations

"""CSV ingestion for the twice-daily Fuel Finder email export."""

import csv
import hashlib
import io
import json
import logging
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.database import get_csv_import, record_csv_import, replace_country_cache

logger = logging.getLogger(__name__)

DATE_FORMAT = "%a %b %d %Y %H:%M:%S GMT%z (Coordinated Universal Time)"

AMENITY_COLUMNS = {
    "forecourts.amenities.fuel_and_energy_services.adblue_pumps": "adblue_pumps",
    "forecourts.amenities.fuel_and_energy_services.adblue_packaged": "adblue_packaged",
    "forecourts.amenities.fuel_and_energy_services.lpg_pumps": "lpg_pumps",
    "forecourts.amenities.vehicle_services.car_wash": "car_wash",
    "forecourts.amenities.air_pump_or_screenwash": "air_pump_or_screenwash",
    "forecourts.amenities.water_filling": "water_filling",
    "forecourts.amenities.twenty_four_hour_fuel": "twenty_four_hour_fuel",
    "forecourts.amenities.customer_toilets": "customer_toilets",
}

CSV_FUEL_COLUMNS = (
    ("E5", "E5"),
    ("E10", "E10"),
    ("B7S", "B7"),
    ("B7P", "SDV"),
    ("HVO", "SDV"),
)

ALLOWED_CSV_DOWNLOAD_HOST = "www.fuel-finder.service.gov.uk"
ALLOWED_CSV_DOWNLOAD_PATH_PREFIX = "/internal/"


@dataclass(frozen=True)
class FuelFinderCsvImport:
    stations: list[dict]
    prices: list[dict]
    rows_seen: int
    rows_skipped: int
    file_sha256: str
    already_imported: bool = False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes", "y"}


def _text(row: dict, key: str, default: str = "") -> str:
    return (row.get(key) or default).strip()


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_timestamp(value: str) -> str:
    value = value.strip()
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.strptime(value, DATE_FORMAT).isoformat()
    except ValueError:
        logger.warning("Could not parse Fuel Finder CSV timestamp: %s", value)
        return datetime.now(timezone.utc).isoformat()


def _normalise_address(row: dict) -> str:
    parts = [
        _text(row, "forecourts.location.address_line_1"),
        _text(row, "forecourts.location.address_line_2"),
        _text(row, "forecourts.location.city"),
        _text(row, "forecourts.location.county"),
    ]
    return ", ".join(part for part in parts if part)


def _normalise_opening_hours(row: dict) -> str:
    days = {}
    for day in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ):
        prefix = f"forecourts.opening_times.usual_days.{day}"
        days[day] = {
            "open_time": _text(row, f"{prefix}.open_time"),
            "close_time": _text(row, f"{prefix}.close_time"),
            "is_24_hours": _truthy(row.get(f"{prefix}.is_24_hours")),
        }
    return json.dumps(days, separators=(",", ":"))


def _normalise_amenities(row: dict) -> list[str]:
    return [
        label
        for column, label in AMENITY_COLUMNS.items()
        if _truthy(row.get(column))
    ]


def parse_fuel_finder_csv_bytes(content: bytes) -> FuelFinderCsvImport:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    stations: list[dict] = []
    prices: list[dict] = []
    rows_seen = 0
    rows_skipped = 0

    for row in reader:
        rows_seen += 1
        if _truthy(row.get("forecourts.permanent_closure")) or _truthy(row.get("forecourts.temporary_closure")):
            rows_skipped += 1
            continue

        station_id = _text(row, "forecourts.node_id")
        lat = _parse_float(_text(row, "forecourts.location.latitude"))
        lng = _parse_float(_text(row, "forecourts.location.longitude"))
        if not station_id or lat is None or lng is None:
            rows_skipped += 1
            continue

        stations.append(
            {
                "station_id": station_id,
                "trading_name": _text(row, "forecourts.trading_name", "Unknown") or "Unknown",
                "brand": _text(row, "forecourts.brand_name") or None,
                "address": _normalise_address(row),
                "postcode": _text(row, "forecourts.location.postcode"),
                "latitude": lat,
                "longitude": lng,
                "amenities": _normalise_amenities(row),
                "opening_hours": _normalise_opening_hours(row),
                "country": "uk",
            }
        )

        prices_by_type: dict[str, dict] = {}
        for csv_code, fuel_type in CSV_FUEL_COLUMNS:
            price = _parse_float(_text(row, f"forecourts.fuel_price.{csv_code}"))
            if price is None:
                continue
            updated_at = _parse_timestamp(
                _text(row, f"forecourts.price_change_effective_timestamp.{csv_code}")
                or _text(row, f"forecourts.price_submission_timestamp.{csv_code}")
                or _text(row, "forecourt_update_timestamp")
            )
            current = prices_by_type.get(fuel_type)
            if current is None or price < current["pence_per_litre"]:
                prices_by_type[fuel_type] = {
                    "station_id": station_id,
                    "fuel_type": fuel_type,
                    "pence_per_litre": price,
                    "updated_at": updated_at,
                }

        prices.extend(prices_by_type.values())

    return FuelFinderCsvImport(
        stations=stations,
        prices=prices,
        rows_seen=rows_seen,
        rows_skipped=rows_skipped,
        file_sha256=hashlib.sha256(content).hexdigest(),
    )


def parse_fuel_finder_csv_file(path: str | Path) -> FuelFinderCsvImport:
    return parse_fuel_finder_csv_bytes(Path(path).read_bytes())


async def import_fuel_finder_csv_bytes(content: bytes) -> FuelFinderCsvImport:
    parsed = parse_fuel_finder_csv_bytes(content)
    existing = await get_csv_import(parsed.file_sha256)
    if existing:
        logger.info("Fuel Finder CSV already imported: sha256=%s", parsed.file_sha256)
        return FuelFinderCsvImport(
            stations=parsed.stations,
            prices=parsed.prices,
            rows_seen=parsed.rows_seen,
            rows_skipped=parsed.rows_skipped,
            file_sha256=parsed.file_sha256,
            already_imported=True,
        )

    await replace_country_cache("uk", parsed.stations, parsed.prices)
    await record_csv_import(
        file_sha256=parsed.file_sha256,
        source="fuel_finder_email_csv",
        stations_count=len(parsed.stations),
        prices_count=len(parsed.prices),
        rows_seen=parsed.rows_seen,
        rows_skipped=parsed.rows_skipped,
    )
    logger.info(
        "Imported Fuel Finder CSV: stations=%d prices=%d skipped=%d sha256=%s",
        len(parsed.stations),
        len(parsed.prices),
        parsed.rows_skipped,
        parsed.file_sha256,
    )
    return parsed


async def import_fuel_finder_csv_file(path: str | Path) -> FuelFinderCsvImport:
    return await import_fuel_finder_csv_bytes(Path(path).read_bytes())


def validate_fuel_finder_csv_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("CSV URL must use https")
    if parsed.netloc != ALLOWED_CSV_DOWNLOAD_HOST:
        raise ValueError("CSV URL host is not allowed")
    if not parsed.path.startswith(ALLOWED_CSV_DOWNLOAD_PATH_PREFIX):
        raise ValueError("CSV URL path is not allowed")
    if "get-latest-fuel-prices-csv" not in parsed.path:
        raise ValueError("CSV URL is not a Fuel Finder CSV download")
    return url


async def download_fuel_finder_csv(url: str) -> bytes:
    validate_fuel_finder_csv_url(url)
    headers = {
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "User-Agent": "Mozilla/5.0 FuelFinderBackend/0.1",
        "Referer": "https://www.fuel-finder.service.gov.uk/",
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        logger.error(
            "Fuel Finder CSV download failed: status=%d url=%s headers=%s body=%s",
            resp.status_code,
            url,
            {
                name: resp.headers.get(name)
                for name in ("server", "date", "content-type", "content-length", "via", "x-cache", "x-amz-cf-pop")
                if resp.headers.get(name)
            },
            resp.text[:500].replace("\n", " "),
        )
        raise
    return resp.content


async def import_fuel_finder_csv_url(url: str) -> FuelFinderCsvImport:
    content = await download_fuel_finder_csv(url)
    return await import_fuel_finder_csv_bytes(content)
