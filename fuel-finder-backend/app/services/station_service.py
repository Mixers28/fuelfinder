from __future__ import annotations

"""Station query service: nearby search, sorting, worth-it recommendation."""

import json
import math
from datetime import datetime
from app.database import get_all_stations_with_fuel, get_station, get_station_prices
from app.models.schemas import (
    StationSummary,
    StationDetail,
    FuelPrice,
    FuelType,
    NearbyResponse,
    WorthItRecommendation,
    FillNowResponse,
    SortBy,
)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in miles."""
    R = 3958.8  # Earth radius in miles
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


_MIN_PRICE_PPL = 80.0   # below this is corrupt data (not real UK pump price)
_MAX_PRICE_PPL = 300.0  # above this is corrupt data


def _row_to_summary(row: dict, user_lat: float, user_lng: float, fuel_type: str) -> StationSummary | None:
    """Returns None if the price is outside the plausible range for UK fuel."""
    dist = haversine_miles(user_lat, user_lng, row["latitude"], row["longitude"])
    price = None
    if "pence_per_litre" in row:
        ppl = row["pence_per_litre"]
        if not (_MIN_PRICE_PPL <= ppl <= _MAX_PRICE_PPL):
            return None
        price = FuelPrice(
            fuel_type=FuelType(fuel_type),
            pence_per_litre=ppl,
            updated_at=row.get("price_updated_at", row.get("updated_at", "2026-01-01T00:00:00Z")),
        )
    return StationSummary(
        station_id=row["station_id"],
        trading_name=row["trading_name"],
        brand=row.get("brand"),
        address=row["address"],
        postcode=row["postcode"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        distance_miles=round(dist, 2),
        price=price,
    )


async def nearby_stations(
    lat: float,
    lng: float,
    fuel_type: FuelType,
    radius_miles: float = 15.0,
    sort_by: SortBy = SortBy.price,
    limit: int = 20,
) -> NearbyResponse:
    """Find stations near (lat, lng) with prices for fuel_type."""
    rows = await get_all_stations_with_fuel(fuel_type.value)

    summaries = []
    for row in rows:
        s = _row_to_summary(row, lat, lng, fuel_type.value)
        if s is not None and s.distance_miles <= radius_miles:
            summaries.append(s)

    # Sort
    if sort_by == SortBy.price:
        summaries.sort(key=lambda s: (s.price.pence_per_litre if s.price else 9999, s.distance_miles))
    else:
        summaries.sort(key=lambda s: (s.distance_miles, s.price.pence_per_litre if s.price else 9999))

    cheapest = min(summaries, key=lambda s: s.price.pence_per_litre, default=None) if summaries else None
    nearest = min(summaries, key=lambda s: s.distance_miles, default=None) if summaries else None

    return NearbyResponse(
        stations=summaries[:limit],
        cheapest=cheapest,
        nearest=nearest,
        total=len(summaries),
        fuel_type=fuel_type,
        user_lat=lat,
        user_lng=lng,
        radius_miles=radius_miles,
    )


async def station_detail(station_id: str) -> StationDetail | None:
    """Full detail for one station including all fuel prices."""
    row = await get_station(station_id)
    if not row:
        return None

    price_rows = await get_station_prices(station_id)
    prices = [
        FuelPrice(
            fuel_type=FuelType(p["fuel_type"]),
            pence_per_litre=p["pence_per_litre"],
            updated_at=p["updated_at"],
        )
        for p in price_rows
        if p["fuel_type"] in ("E10", "E5", "B7", "SDV")
    ]

    amenities = json.loads(row.get("amenities", "[]")) if isinstance(row.get("amenities"), str) else row.get("amenities", [])

    return StationDetail(
        station_id=row["station_id"],
        trading_name=row["trading_name"],
        brand=row.get("brand"),
        address=row["address"],
        postcode=row["postcode"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        amenities=amenities,
        opening_hours=row.get("opening_hours"),
        prices=prices,
    )


def compute_worth_it(
    target: StationSummary,
    baseline: StationSummary,
    tank_litres: float = 40.0,
    mpg: float = 35.0,
) -> WorthItRecommendation:
    """Should the user drive to target instead of filling at baseline?

    Compares fuel cost saving on a full tank vs extra fuel burned
    for the round-trip detour. Assumes baseline is the nearest station.
    """
    if not target.price or not baseline.price:
        return WorthItRecommendation(
            recommended_station_id=baseline.station_id,
            recommended_station_name=baseline.trading_name,
            net_saving_pence=0,
            extra_miles_round_trip=0,
            saving_per_litre_pence=0,
            worth_driving=False,
            explanation="Insufficient price data for comparison.",
        )

    saving_per_litre = baseline.price.pence_per_litre - target.price.pence_per_litre
    extra_miles = max(0, (target.distance_miles - baseline.distance_miles) * 2)

    # Extra fuel cost for the detour
    litres_per_gallon = 4.546
    extra_fuel_litres = (extra_miles / mpg) * litres_per_gallon if mpg > 0 else 0
    extra_fuel_cost_pence = extra_fuel_litres * target.price.pence_per_litre

    # Saving on a full tank
    tank_saving_pence = saving_per_litre * tank_litres
    net_saving = tank_saving_pence - extra_fuel_cost_pence
    worth_it = net_saving > 0 and saving_per_litre > 0

    if worth_it:
        explanation = (
            f"Save {saving_per_litre:.1f}p/L at {target.trading_name}. "
            f"Extra {extra_miles:.1f} mile round trip costs ~{extra_fuel_cost_pence:.0f}p in fuel. "
            f"Net saving ~{net_saving:.0f}p on a {tank_litres:.0f}L fill."
        )
        rec_id = target.station_id
        rec_name = target.trading_name
    else:
        explanation = (
            f"Cheapest is {target.trading_name} ({saving_per_litre:.1f}p/L less), "
            f"but the {extra_miles:.1f} mile detour wipes out the saving. "
            f"Fill at {baseline.trading_name} instead."
        )
        rec_id = baseline.station_id
        rec_name = baseline.trading_name

    return WorthItRecommendation(
        recommended_station_id=rec_id,
        recommended_station_name=rec_name,
        net_saving_pence=round(net_saving),
        extra_miles_round_trip=round(extra_miles, 1),
        saving_per_litre_pence=round(saving_per_litre, 1),
        worth_driving=worth_it,
        explanation=explanation,
    )


async def fill_now_recommendation(
    lat: float,
    lng: float,
    fuel_type: FuelType,
    radius_miles: float = 15.0,
    tank_litres: float = 40.0,
) -> FillNowResponse | None:
    """The main "should I drive further?" recommendation."""
    result = await nearby_stations(lat, lng, fuel_type, radius_miles, SortBy.price, limit=50)
    if not result.cheapest or not result.nearest:
        return None

    recommendation = compute_worth_it(
        target=result.cheapest,
        baseline=result.nearest,
        tank_litres=tank_litres,
    )

    return FillNowResponse(
        fuel_type=fuel_type,
        cheapest=result.cheapest,
        nearest=result.nearest,
        recommendation=recommendation,
    )
