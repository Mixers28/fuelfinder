"""API routes for station lookup."""

from fastapi import APIRouter, HTTPException, Query
from app.models.schemas import (
    FuelType,
    SortBy,
    NearbyResponse,
    StationDetail,
    FillNowResponse,
)
from app.services.station_service import (
    nearby_stations,
    station_detail,
    fill_now_recommendation,
)

router = APIRouter(prefix="/api", tags=["stations"])


@router.get("/stations/nearby", response_model=NearbyResponse)
async def get_nearby_stations(
    lat: float = Query(..., description="User latitude"),
    lng: float = Query(..., description="User longitude"),
    fuel_type: FuelType = Query(FuelType.E10, description="Fuel type to search"),
    radius: float = Query(15.0, ge=0.5, le=50, description="Search radius in miles"),
    sort: SortBy = Query(SortBy.price, description="Sort order"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
):
    """Find nearby stations with prices for the selected fuel type."""
    return await nearby_stations(lat, lng, fuel_type, radius, sort, limit)


@router.get("/stations/{station_id}", response_model=StationDetail)
async def get_station(station_id: str):
    """Full detail for a single station including all fuel prices."""
    result = await station_detail(station_id)
    if not result:
        raise HTTPException(status_code=404, detail="Station not found")
    return result


@router.get("/stations/{station_id}/price-history")
async def get_price_history(station_id: str):
    """Price history for a station.

    NOTE: This endpoint requires accumulating snapshots over time.
    MVP returns current price only. Implement a scheduled job to
    append to a price_history table before enabling this properly.
    """
    result = await station_detail(station_id)
    if not result:
        raise HTTPException(status_code=404, detail="Station not found")
    return {
        "station_id": station_id,
        "note": "Price history requires time-series accumulation. MVP returns current snapshot only.",
        "current_prices": result.prices,
    }


@router.get("/recommendation/fill-now", response_model=FillNowResponse)
async def get_fill_recommendation(
    lat: float = Query(..., description="User latitude"),
    lng: float = Query(..., description="User longitude"),
    fuel_type: FuelType = Query(FuelType.E10),
    radius: float = Query(15.0, ge=0.5, le=50),
    tank_litres: float = Query(40.0, ge=10, le=100, description="Tank size in litres"),
):
    """Should the user drive further for cheaper fuel?"""
    result = await fill_now_recommendation(lat, lng, fuel_type, radius, tank_litres)
    if not result:
        raise HTTPException(status_code=404, detail="No stations found in range")
    return result
