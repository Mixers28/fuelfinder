"""Dutch integration checks through the ASGI API, SQLite and mocked Petromap v2."""

import asyncio
import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app import database
from app.main import app
from app.services import petromap_client as petromap, station_service
from app.services.german_search import GermanArea
from app.services.geo import haversine_miles, KM_PER_MILE


FUELS = [
    {"token": "petrol_95_e10", "family": "petrol", "grade": "standard", "octane": 95,
     "additised": False, "en16942": "E10", "unit": "L"},
    {"token": "petrol_95_e5", "family": "petrol", "grade": "standard", "octane": 95,
     "additised": False, "en16942": "E5", "unit": "L"},
    {"token": "petrol_98_e5", "family": "petrol", "grade": "premium", "octane": 98,
     "additised": False, "en16942": "E5", "unit": "L"},
    {"token": "diesel_b7", "family": "diesel", "grade": "standard", "octane": None,
     "additised": False, "en16942": "B7", "unit": "L"},
    # Deliberately arbitrary: premium tokens must come from the catalogue.
    {"token": "premium_diesel_fixture", "family": "diesel", "grade": "premium", "octane": None,
     "additised": True, "en16942": "B7", "unit": "L"},
]


def place(public_id="NL01000123", lat=52.3676, lng=4.9041, amount=1.999):
    return {
        "id": public_id, "kind": "fuel", "country": "NL", "name": f"Station {public_id}",
        "city": "Amsterdam", "street": "Example Street 1", "postalCode": "1012 JS",
        "location": {"lat": lat, "lon": lng}, "openNow": True,
        "network": {"id": "NL_TEST", "name": "Test", "group": "test"},
        "hours": {"alwaysOpen": True}, "amenities": ["carwash", "restroom", "shop"],
        "fuels": [{**f, "price": {"amount": amount, "currency": "EUR",
                   "updatedAt": "2026-10-02T11:22:33.789Z"}} for f in FUELS],
    }


class PetromapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc).timestamp()
        self.settings = SimpleNamespace(petromap_api_key="test-server-secret")
        self.requests = []
        self.places = [place()]
        self.fuels = copy.deepcopy(FUELS)
        self.override = None
        self.timeout = False
        self.page_size = 100
        self.repeat_cursor = False
        self.fail_second_page = False
        self.german_stations = []

        async def german_search(lat, lng, radius):
            return GermanArea(self.german_stations, radius)

        for target, attribute, value in (
            (database, "DB_PATH", Path(directory.name) / "test.db"),
            (database, "time", lambda: self.now),
            (petromap, "get_settings", lambda: self.settings),
            (petromap, "time", lambda: self.now),
            (petromap, "_refresh_lock", None),
            (station_service, "get_german_stations", german_search),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        await database.init_db()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        original_client = httpx.AsyncClient
        patcher = patch.object(petromap.httpx, "AsyncClient", side_effect=lambda **kwargs:
            original_client(transport=httpx.MockTransport(self.provider_response), **kwargs)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def provider_response(self, request):
        self.requests.append(request)
        await asyncio.sleep(0)
        if self.timeout:
            raise httpx.ReadTimeout("test-server-secret", request=request)
        if self.override is not None:
            return self.override
        if request.url.path == "/v2/fuels":
            return httpx.Response(200, json={"families": ["petrol", "diesel"], "fuels": self.fuels})
        if request.url.path.startswith("/v2/places/"):
            station = next((p for p in self.places if p["id"] == request.url.path.split("/")[-1]), None)
            return httpx.Response(200, json={"place": station, "credits": 1}) if station else httpx.Response(404)
        self.assertEqual(request.url.path, "/v2/places")
        if self.fail_second_page and "cursor" in request.url.params:
            return httpx.Response(503)
        token = request.url.params["fuel"]
        stations = []
        for station in self.places:
            summary = {k: v for k, v in station.items() if k not in ("fuels", "hours", "amenities")}
            summary["fuel"] = next((f for f in station.get("fuels", []) if f["token"] == token), None)
            stations.append(summary)
        start = int(request.url.params.get("cursor", "0"))
        end = start + self.page_size
        cursor = str(end) if end < len(stations) else None
        if self.repeat_cursor:
            cursor = "1"
        return httpx.Response(200, json={"places": stations[start:end], "credits": 1, "nextCursor": cursor})

    async def nearby(self, **params):
        return await self.client.get("/stations/nearby", params={"lat": 52.3676, "lng": 4.9041, **params})

    @property
    def search_requests(self):
        return [r for r in self.requests if r.url.path == "/v2/places"]

    async def test_search_uses_server_auth_exact_grade_coarse_area_and_euro_cents(self):
        response = await self.nearby()
        self.assertEqual(response.status_code, 200, response.text)
        station = response.json()["stations"][0]
        self.assertEqual(station["station_id"], "nl_pm_NL01000123")
        self.assertEqual(station["price"], {"fuel_type": "E10", "pence_per_litre": 199.9,
                         "updated_at": "2026-10-02T11:22:33Z", "currency": "EUR"})
        request = self.search_requests[0]
        self.assertEqual(request.headers["x-api-key"], "test-server-secret")
        self.assertNotIn("test-server-secret", str(request.url))
        self.assertEqual(dict(request.url.params), {
            "filter": "circle:4.90,52.37,26000", "fuel": "petrol_95_e10",
            "country": "NL", "currency": "EUR", "unpriced": "exclude", "sort": "distance",
        })
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_sorts_limit_nearby_coordinates_and_recommendation_share_cache(self):
        self.places.append(place("NL01000124", lat=52.4, amount=1.799))
        nearest = await self.nearby(sort="distance", limit=1)
        cheapest = await self.nearby(sort="price", limit=1, lat=52.3677, lng=4.9042)
        self.assertEqual(nearest.json()["stations"][0]["station_id"], "nl_pm_NL01000123")
        self.assertEqual(cheapest.json()["stations"][0]["station_id"], "nl_pm_NL01000124")
        self.assertEqual(nearest.json()["total"], 2)
        self.assertEqual(nearest.json()["cheapest"]["station_id"], "nl_pm_NL01000124")
        recommendation = await self.client.get("/recommendation/fill-now", params={"lat": 52.3676, "lng": 4.9041})
        self.assertEqual(recommendation.status_code, 200)
        self.assertIn("c/L", recommendation.json()["recommendation"]["explanation"])
        self.assertEqual(len(self.search_requests), 1)

    async def test_concurrent_requests_fetch_once_and_survive_process_state_reset(self):
        responses = await asyncio.gather(*[self.nearby() for _ in range(4)])
        self.assertEqual([r.status_code for r in responses], [200] * 4)
        petromap._refresh_lock = None
        self.assertEqual((await self.nearby()).status_code, 200)
        self.assertEqual(len(self.search_requests), 1)

    async def test_each_fuel_uses_its_exact_catalogue_token(self):
        for fuel, token in (("E10", "petrol_95_e10"), ("E5", "petrol_98_e5"),
                            ("B7", "diesel_b7"), ("SDV", "premium_diesel_fixture")):
            response = await self.nearby(fuel_type=fuel)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["stations"][0]["price"]["fuel_type"], fuel)
            self.assertEqual(self.search_requests[-1].url.params["fuel"], token)
        self.assertEqual(len([r for r in self.requests if r.url.path == "/v2/fuels"]), 1)

    async def test_unsupported_grade_is_explained_without_a_paid_search(self):
        self.fuels = [f for f in self.fuels if f["token"] != "premium_diesel_fixture"]
        response = await self.nearby(fuel_type="SDV")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        self.assertIn("Try another fuel", response.json()["notice"])
        self.assertEqual(self.search_requests, [])

    async def test_pagination_preserves_filters_and_finds_cheapest_on_later_page(self):
        self.page_size = 1
        self.places.append(place("NL01000124", lat=52.4, amount=1.799))
        response = await self.nearby(limit=1)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["cheapest"]["station_id"], "nl_pm_NL01000124")
        self.assertEqual(len(self.search_requests), 2)
        first, second = [dict(r.url.params) for r in self.search_requests]
        self.assertEqual(second.pop("cursor"), "1")
        self.assertEqual(first, second)

    async def test_incomplete_pagination_never_becomes_a_partial_cache(self):
        self.page_size = 1
        self.places.append(place("NL01000124"))
        self.fail_second_page = True
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(await database.get_petromap_cache("area:52.37,4.90:26000:E10", self.now))

    async def test_cursor_cycles_and_page_limit_do_not_return_partial_comparisons(self):
        self.repeat_cursor = True
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(self.search_requests), 2)
        self.now += 61
        self.repeat_cursor = False
        self.page_size = 1
        self.places.append(place("NL01000124"))
        with patch.object(petromap, "MAX_PAGES", 1):
            response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertIn("smaller radius", response.json()["detail"])

    async def test_successful_empty_results_are_cached(self):
        self.places = []
        for _ in range(2):
            response = await self.nearby()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 0)
        self.assertEqual(len(self.search_requests), 1)

    async def test_closed_unpriced_wrong_currency_and_invalid_source_times_are_excluded(self):
        self.places = [place(f"NL0000000{i}") for i in range(6)]
        self.places[0]["openNow"] = False
        self.places[1]["fuels"][0]["price"] = None
        self.places[2]["fuels"][0]["price"]["currency"] = "GBP"
        self.places[3]["fuels"][0]["price"]["updatedAt"] = "invalid"
        self.places[4]["fuels"][0]["price"]["updatedAt"] = "2099-01-01T00:00:00Z"
        self.places[5]["fuels"][0]["price"]["amount"] = True
        response = await self.nearby()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 0)

    async def test_wrong_grade_is_not_substituted_for_requested_super_unleaded(self):
        self.places[0]["fuels"] = [self.places[0]["fuels"][1]]  # 95 E5, not 98 E5.
        response = await self.nearby(fuel_type="E5")
        self.assertEqual(response.json()["total"], 0)

    async def test_malformed_responses_are_safe_errors_without_partial_station_storage(self):
        for body in ([], {"places": []}, {"error": "test-server-secret"},
                     {"fuels": [None]}, {"fuels": []}):
            self.override = httpx.Response(200, json=body)
            response = await self.nearby()
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn("test-server-secret", response.text)
            self.now += 61
        self.override = None
        self.places[0]["location"] = {"lat": "bad", "lon": 4.9}
        self.assertEqual((await self.nearby()).status_code, 503)
        self.assertIsNone(await database.get_station("nl_pm_NL01000123"))

    async def test_three_hour_refresh_preserves_source_age_and_removes_missing_prices(self):
        first = await self.nearby()
        self.now += petromap.CACHE_SECONDS
        refreshed = await self.nearby()
        self.assertEqual(refreshed.json()["stations"][0]["price"]["updated_at"],
                         first.json()["stations"][0]["price"]["updated_at"])
        self.now += petromap.CACHE_SECONDS
        self.places[0]["fuels"][0]["price"] = None
        self.assertEqual((await self.nearby()).json()["total"], 0)
        self.assertEqual(len(self.search_requests), 3)

    async def test_expired_results_are_deleted_not_returned_during_an_outage(self):
        await self.nearby()
        self.now += petromap.CACHE_SECONDS + 1
        self.timeout = True
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("test-server-secret", response.text)
        self.assertIsNone(await database.get_petromap_cache("area:52.37,4.90:26000:E10", self.now))

    async def test_pruning_on_startup_and_maintenance_deletes_station_and_catalogue_cache(self):
        await self.nearby()
        await self.client.get("/stations/nl_pm_NL01000123")
        self.now += 24 * 3600
        await database.init_db()
        for key in ("fuels", "area:52.37,4.90:26000:E10", "detail:NL01000123"):
            self.assertIsNone(await database.get_petromap_cache(key, self.now))
        self.assertIsNone(await database.get_station("nl_pm_NL01000123"))
        self.assertEqual(await database.get_station_prices("nl_pm_NL01000123"), [])

    async def test_missing_key_never_contacts_provider_or_claims_no_stations(self):
        self.settings.petromap_api_key = ""
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.requests, [])

    async def test_authentication_errors_and_timeouts_have_shared_backoff(self):
        for status in (401, 403, 500):
            self.override = httpx.Response(status, json={"error": "test-server-secret"})
            response = await self.nearby()
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("test-server-secret", response.text)
            count = len(self.requests)
            response = await self.nearby(lat=52.1)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(len(self.requests), count)
            self.now += 301

    async def test_daily_budget_exhaustion_waits_until_midnight_utc(self):
        for code in ("DAILY_BUDGET_EXHAUSTED", "INSUFFICIENT_CREDITS"):
            self.override = httpx.Response(429, json={"error": code})
            response = await self.nearby()
            self.assertEqual(response.status_code, 503)
            self.assertIn("midnight UTC", response.json()["detail"])
            wait = int(response.headers["Retry-After"])
            self.assertGreater(wait, 0)
            self.assertLessEqual(wait, 86400)
            count = len(self.requests)
            self.now += 60
            petromap._refresh_lock = None
            self.assertEqual((await self.nearby()).headers["Retry-After"], str(wait - 60))
            self.assertEqual(len(self.requests), count)
            self.now += wait - 60
        self.override = None
        self.assertEqual((await self.nearby()).status_code, 200)

    async def test_rate_limit_honours_retry_after_but_fresh_cache_stays_usable(self):
        await self.nearby()
        self.override = httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "RATE_LIMITED"})
        response = await self.nearby(lat=52.1)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.assertEqual((await self.nearby()).status_code, 200)

    async def test_fractional_time_retries_do_not_extend_provider_cooldown(self):
        self.override = httpx.Response(429, headers={"Retry-After": "2"})
        self.assertEqual((await self.nearby()).headers["Retry-After"], "2")
        self.now += 0.5
        self.assertEqual((await self.nearby()).headers["Retry-After"], "2")
        self.now += 1.5
        self.override = None
        self.assertEqual((await self.nearby()).status_code, 200)

    async def test_invalid_optional_metadata_cannot_poison_a_detail_cache(self):
        for change in ({"network": {"name": 123}}, {"postalCode": []}, {"amenities": [None]}):
            self.places = [{**place(), **change}]
            response = await self.client.get("/stations/nl_pm_NL01000123")
            self.assertEqual(response.status_code, 503, response.text)
            self.assertIsNone(await database.get_petromap_cache("detail:NL01000123", self.now))
            self.now += 61

    async def test_detail_loads_all_supported_grades_and_reuses_its_own_cache(self):
        for _ in range(2):
            response = await self.client.get("/stations/nl_pm_NL01000123")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual({p["fuel_type"] for p in response.json()["prices"]}, {"E10", "E5", "B7", "SDV"})
            self.assertEqual(response.json()["amenities"], ["car_wash", "restroom", "shop"])
            self.assertTrue(all(p["currency"] == "EUR" for p in response.json()["prices"]))
        self.assertEqual(len([r for r in self.requests if r.url.path.startswith("/v2/places/")]), 1)
        self.assertIsNone(await database.get_station("nl_pm_NL01000123"))

    async def test_detail_expiry_removes_closed_station_prices(self):
        await self.client.get("/stations/nl_pm_NL01000123")
        self.now += petromap.CACHE_SECONDS
        self.places[0]["openNow"] = False
        response = await self.client.get("/stations/nl_pm_NL01000123")
        self.assertEqual(response.json()["prices"], [])

    async def test_invalid_and_unknown_ids_return_not_found(self):
        self.assertEqual((await self.client.get("/stations/nl_pm_bad-id")).status_code, 404)
        self.assertEqual(self.requests, [])
        for _ in range(2):
            self.assertEqual((await self.client.get("/stations/nl_pm_NL99999999")).status_code, 404)
        self.assertEqual(len([r for r in self.requests if r.url.path.startswith("/v2/places/")]), 1)

    async def test_large_radius_is_capped_and_grid_padding_covers_the_displayed_area(self):
        response = await self.nearby(radius=50)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("within", body["notice"])
        radius_metres = int(self.search_requests[0].url.params["filter"].split(",")[-1])
        self.assertLessEqual(radius_metres, 50000)
        offset = haversine_miles(52.3676, 4.9041, 52.37, 4.90)
        self.assertLessEqual((body["radius_miles"] + offset) * KM_PER_MILE * 1000, radius_metres)

    async def test_missing_dutch_provider_does_not_break_german_border_results(self):
        self.settings.petromap_api_key = ""
        self.german_stations = [{
            "station_id": "de_border", "trading_name": "German station", "country": "de",
            "address": "Road", "postcode": "12345", "latitude": 51.37, "longitude": 6.25,
            "prices": [{"fuel_type": "E10", "pence_per_litre": 190, "updated_at": "2026-10-02T11:22:33Z"}],
        }]
        response = await self.nearby(lat=51.37, lng=6.17)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 1)
        self.assertIn("German stations only", response.json()["notice"])

    async def test_retired_anwb_prices_are_never_used(self):
        await database.bulk_upsert_stations([{
            "station_id": "nl_old", "trading_name": "Old cheap station", "country": "nl",
            "address": "Old Road", "postcode": "1012 JS", "latitude": 52.3676, "longitude": 4.9041,
        }])
        await database.bulk_upsert_prices([{
            "station_id": "nl_old", "fuel_type": "E10", "pence_per_litre": 101,
            "updated_at": "2025-01-01T00:00:00Z",
        }])
        response = await self.nearby()
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["cheapest"]["station_id"], "nl_pm_NL01000123")
        self.assertEqual((await self.client.get("/stations/nl_old")).status_code, 404)


if __name__ == "__main__":
    unittest.main()
