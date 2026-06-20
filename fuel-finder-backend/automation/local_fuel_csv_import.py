from __future__ import annotations

"""Download latest Fuel Finder CSV locally and upload it to the backend.

This is intended for a trusted machine/network when cloud runtimes are blocked
from downloading Fuel Finder CSVs directly.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_CSV_URL = "https://www.fuel-finder.service.gov.uk/internal/v1.0.2/csv/get-latest-fuel-prices-csv"


def _read_url(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read(), response.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code} {body[:500]}") from exc


def _post_csv(import_url: str, admin_token: str, csv_bytes: bytes) -> tuple[int, str]:
    request = urllib.request.Request(
        import_url,
        data=csv_bytes,
        headers={
            "content-type": "text/csv",
            "x-admin-token": admin_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"POST {import_url} failed: HTTP {exc.code} {body[:1000]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Import latest Fuel Finder CSV into Railway backend.")
    parser.add_argument("--csv-url", default=os.environ.get("FUEL_FINDER_CSV_URL", DEFAULT_CSV_URL))
    parser.add_argument("--import-url", default=os.environ.get("FUEL_FINDER_IMPORT_URL"))
    parser.add_argument("--admin-token", default=os.environ.get("ADMIN_IMPORT_TOKEN"))
    args = parser.parse_args()

    if not args.import_url:
        print("Missing --import-url or FUEL_FINDER_IMPORT_URL", file=sys.stderr)
        return 2
    if not args.admin_token:
        print("Missing --admin-token or ADMIN_IMPORT_TOKEN", file=sys.stderr)
        return 2

    status, csv_bytes, content_type = _read_url(
        args.csv_url,
        headers={
            "accept": "text/csv,*/*",
            "user-agent": "FuelFinderLocalImporter/0.1",
        },
    )
    if not csv_bytes:
        raise RuntimeError("Downloaded CSV was empty")

    post_status, body = _post_csv(args.import_url, args.admin_token, csv_bytes)
    try:
        parsed = json.loads(body)
        body_summary = json.dumps(parsed, sort_keys=True)
    except json.JSONDecodeError:
        body_summary = body

    print(f"Downloaded CSV: status={status} bytes={len(csv_bytes)} content_type={content_type}")
    print(f"Uploaded CSV: status={post_status} response={body_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
