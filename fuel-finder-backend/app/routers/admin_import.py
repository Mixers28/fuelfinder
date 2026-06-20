from __future__ import annotations

"""Admin-only import endpoints."""

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings
from app.services.fuel_finder_csv import import_fuel_finder_csv_bytes, import_fuel_finder_csv_url

router = APIRouter(prefix="/admin", tags=["admin"])


class FuelFinderCsvUrlImportRequest(BaseModel):
    url: str


def _require_admin_token(x_admin_token: str | None):
    expected = get_settings().admin_import_token
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/import/fuel-finder-csv")
async def import_fuel_finder_csv(
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="CSV body is empty")

    parsed = await import_fuel_finder_csv_bytes(content)
    return {
        "ok": True,
        "already_imported": parsed.already_imported,
        "stations": len(parsed.stations),
        "prices": len(parsed.prices),
        "rows_seen": parsed.rows_seen,
        "rows_skipped": parsed.rows_skipped,
        "file_sha256": parsed.file_sha256,
    }


@router.post("/import/fuel-finder-csv-url")
async def import_fuel_finder_csv_from_url(
    payload: FuelFinderCsvUrlImportRequest,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    try:
        parsed = await import_fuel_finder_csv_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Fuel Finder CSV download failed",
                "upstream_status": exc.response.status_code,
            },
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Fuel Finder CSV download request failed",
                "error": str(exc),
            },
        ) from exc

    return {
        "ok": True,
        "already_imported": parsed.already_imported,
        "stations": len(parsed.stations),
        "prices": len(parsed.prices),
        "rows_seen": parsed.rows_seen,
        "rows_skipped": parsed.rows_skipped,
        "file_sha256": parsed.file_sha256,
    }
