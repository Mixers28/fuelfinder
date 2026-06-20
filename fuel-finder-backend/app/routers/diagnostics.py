from __future__ import annotations

"""Operational diagnostics endpoints.

These routes are disabled unless DIAGNOSTICS_TOKEN is set.
"""

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.fuel_finder_client import fuel_finder_client

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


def _require_diagnostics_token(x_diagnostics_token: str | None):
    expected = get_settings().diagnostics_token
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if x_diagnostics_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/fuel-finder-token")
async def diagnose_fuel_finder_token(x_diagnostics_token: str | None = Header(default=None)):
    _require_diagnostics_token(x_diagnostics_token)
    return await fuel_finder_client.diagnose_token_request()
