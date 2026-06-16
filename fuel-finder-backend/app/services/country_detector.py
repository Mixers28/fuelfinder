from __future__ import annotations

# Bounding boxes — deliberately generous to avoid edge cases near borders.
# Returns ISO country code: 'uk', 'nl', 'de'
_BOXES = {
    "uk": dict(lat_min=49.9, lat_max=61.0, lng_min=-8.2, lng_max=1.8),
    "nl": dict(lat_min=50.7, lat_max=53.6, lng_min=3.3,  lng_max=7.3),
    "de": dict(lat_min=47.3, lat_max=55.1, lng_min=5.9,  lng_max=15.1),
}

# NL/DE boxes overlap slightly — NL takes priority since it's smaller.
_PRIORITY = ["nl", "de", "uk"]


def detect_country(lat: float, lng: float) -> str:
    for code in _PRIORITY:
        b = _BOXES[code]
        if b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]:
            return code
    return "uk"


CURRENCY_FOR_COUNTRY = {
    "uk": "GBP",
    "nl": "EUR",
    "de": "EUR",
}
