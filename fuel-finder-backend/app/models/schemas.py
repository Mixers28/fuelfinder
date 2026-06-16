from __future__ import annotations

"""API models — request/response schemas."""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class FuelType(str, Enum):
    E10 = "E10"
    E5 = "E5"
    B7 = "B7"
    SDV = "SDV"


class SortBy(str, Enum):
    price = "price"
    distance = "distance"


# ── Response models ──


class FuelPrice(BaseModel):
    fuel_type: FuelType
    pence_per_litre: float   # minor currency units per litre (pence for GBP, cents for EUR)
    updated_at: datetime
    currency: str = "GBP"   # ISO 4217: GBP, EUR


class StationSummary(BaseModel):
    station_id: str
    trading_name: str
    brand: str | None = None
    address: str
    postcode: str
    latitude: float
    longitude: float
    distance_miles: float
    price: FuelPrice | None = None
    country: str = "uk"


class StationDetail(BaseModel):
    station_id: str
    trading_name: str
    brand: str | None = None
    address: str
    postcode: str
    latitude: float
    longitude: float
    amenities: list[str] = []
    opening_hours: str | None = None
    prices: list[FuelPrice] = []
    country: str = "uk"


class NearbyResponse(BaseModel):
    stations: list[StationSummary]
    cheapest: StationSummary | None = None
    nearest: StationSummary | None = None
    total: int
    fuel_type: FuelType
    user_lat: float
    user_lng: float
    radius_miles: float


class WorthItRecommendation(BaseModel):
    recommended_station_id: str
    recommended_station_name: str
    net_saving_pence: int
    extra_miles_round_trip: float
    saving_per_litre_pence: float
    worth_driving: bool
    explanation: str


class FillNowResponse(BaseModel):
    fuel_type: FuelType
    cheapest: StationSummary
    nearest: StationSummary
    recommendation: WorthItRecommendation
