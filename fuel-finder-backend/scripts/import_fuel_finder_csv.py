from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import init_db
from app.services.fuel_finder_csv import import_fuel_finder_csv_file


async def main():
    parser = argparse.ArgumentParser(description="Import a Fuel Finder email CSV into the local cache.")
    parser.add_argument("csv_path", help="Path to UpdatedFuelPrice CSV file")
    args = parser.parse_args()

    await init_db()
    parsed = await import_fuel_finder_csv_file(args.csv_path)
    print(f"Already imported: {parsed.already_imported}")
    print(f"Imported {len(parsed.stations)} UK stations")
    print(f"Imported {len(parsed.prices)} UK prices")
    print(f"Rows seen: {parsed.rows_seen}")
    print(f"Rows skipped: {parsed.rows_skipped}")
    print(f"SHA256: {parsed.file_sha256}")


if __name__ == "__main__":
    asyncio.run(main())
