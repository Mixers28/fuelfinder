from __future__ import annotations

# Bounding boxes — deliberately generous to avoid edge cases near borders.
# Returns ISO country code: 'uk', 'nl', 'de'
_BOXES = {
    "uk": dict(lat_min=49.9, lat_max=61.0, lng_min=-8.2, lng_max=1.8),
    "nl": dict(lat_min=50.7, lat_max=53.6, lng_min=3.3,  lng_max=7.3),
    "de": dict(lat_min=47.25, lat_max=55.1, lng_min=5.85, lng_max=15.1),
}

# These are approximate regions, not country borders: the NL box also covers
# German cities such as Düsseldorf and Cologne. Nearby searches must consider
# both DE and NL stations and filter by distance, rather than exclude a provider
# based on this hint alone.
_PRIORITY = ["nl", "de", "uk"]


def in_country_box(lat: float, lng: float, country: str) -> bool:
    b = _BOXES[country]
    return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]


def detect_country(lat: float, lng: float) -> str:
    for code in _PRIORITY:
        if in_country_box(lat, lng, code):
            return code
    return "uk"


CURRENCY_FOR_COUNTRY = {
    "uk": "GBP",
    "nl": "EUR",
    "de": "EUR",
}
