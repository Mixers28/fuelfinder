"""Exercise on-demand searches through the real API, cache and provider client."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from time import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app import database
from app.main import app
from app.services import german_search, tankerkoenig_client, station_service
from app.services.petromap_client import DutchArea
from app.services.geo import KM_PER_MILE, haversine_miles


class GermanOnDemandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = SimpleNamespace(
            tankerkoenig_api_key="test-private-key", price_cache_ttl=900,
            tankerkoenig_stale_ttl=3600,
        )
        self.now = time()
        self.requests = []
        self.response_override = None
        self.timeout = False
        self.dutch_stations = []
        async def dutch_search(lat, lng, radius, fuel):
            return DutchArea(self.dutch_stations, radius)
        dutch_patch = patch.object(station_service, "get_dutch_stations", side_effect=dutch_search)
        dutch_patch.start()
        self.addCleanup(dutch_patch.stop)
        self.provider_stations = [{
            "id": "hanover", "name": "Hanover Station", "brand": "Test",
            "lat": 52.3759, "lng": 9.7320, "postCode": 30159,
            "street": "Test Street", "houseNumber": "1", "isOpen": True,
            "e10": 1.799, "e5": 1.859, "diesel": 1.699,
        }]
        for target, attribute, value in (
            (database, "DB_PATH", Path(directory.name) / "test.db"),
            (german_search, "get_settings", lambda: self.settings),
            (tankerkoenig_client, "get_settings", lambda: self.settings),
            (german_search, "time", lambda: self.now),
            (german_search, "_refresh_lock", None),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        await database.init_db()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)
        original_client = httpx.AsyncClient
        provider_patch = patch.object(tankerkoenig_client.httpx, "AsyncClient", side_effect=lambda **kwargs:
            original_client(transport=httpx.MockTransport(self.provider_response), **kwargs)
        )
        provider_patch.start()
        self.addCleanup(provider_patch.stop)

    async def provider_response(self, request):
        self.requests.append(request)
        await asyncio.sleep(0)  # Allow overlapping requests to exercise deduplication.
        if self.timeout:
            raise httpx.ReadTimeout("provider timeout", request=request)
        if self.response_override is not None:
            return self.response_override
        lat, lng = float(request.url.params["lat"]), float(request.url.params["lng"])
        stations = [s.copy() for s in self.provider_stations
                    if haversine_miles(lat, lng, s["lat"], s["lng"]) * KM_PER_MILE <= 25]
        return httpx.Response(200, json={"ok": True, "stations": stations})

    async def nearby(self, **params):
        return await self.client.get("/api/stations/nearby", params={
            "lat": 52.3759, "lng": 9.7320, **params,
        })

    async def test_hanover_fetches_on_first_search_without_any_preloaded_stations(self):
        response = await self.nearby()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["stations"][0]["station_id"], "de_hanover")
        self.assertEqual(body["stations"][0]["price"]["currency"], "EUR")
        self.assertEqual(body["stations"][0]["price"]["pence_per_litre"], 179.9)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(float(self.requests[0].url.params["lat"]), 52.38)
        self.assertEqual(float(self.requests[0].url.params["lng"]), 9.73)
        self.assertEqual(float(self.requests[0].url.params["rad"]), 25)
        self.assertEqual(self.requests[0].url.params["type"], "all")
        cached = await database.get_german_area("52.38,9.73")
        self.assertNotIn("user_lat", json.dumps(cached))

    async def test_a_rural_location_also_fetches_on_demand(self):
        self.provider_stations[0].update(id="rural", lat=50.98, lng=10.32)
        response = await self.nearby(lat=50.9801, lng=10.3202)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["stations"][0]["station_id"], "de_rural")
        self.assertEqual(len(self.requests), 1)

    async def test_fuels_sorting_recommendations_and_details_share_one_fetch(self):
        for fuel in ("E10", "E5", "B7"):
            response = await self.nearby(fuel_type=fuel, sort="distance", limit=1)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["stations"][0]["price"]["fuel_type"], fuel)
        recommendation = await self.client.get("/recommendation/fill-now", params={
            "lat": 52.3759, "lng": 9.7320,
        })
        self.assertEqual(recommendation.status_code, 200, recommendation.text)
        detail = await self.client.get("/stations/de_hanover")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(len(detail.json()["prices"]), 3)
        self.assertEqual(len(self.requests), 1)

    async def test_concurrent_searches_for_same_area_fetch_once(self):
        responses = await asyncio.gather(*[self.nearby() for _ in range(4)])
        self.assertEqual([r.status_code for r in responses], [200] * 4)
        self.assertEqual(len(self.requests), 1)

    async def test_nearby_coordinates_in_same_grid_cell_reuse_cache(self):
        await self.nearby()
        response = await self.nearby(lat=52.3761, lng=9.7322)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.requests), 1)

    async def test_successful_empty_area_is_cached(self):
        self.provider_stations = []
        for _ in range(2):
            response = await self.nearby()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 0)
            self.assertIsNone(response.json()["notice"])
        self.assertEqual(len(self.requests), 1)

    async def test_new_area_is_throttled_then_can_be_requested_after_a_minute(self):
        await self.nearby()
        self.provider_stations[0].update(id="erfurt", lat=50.98, lng=11.03)
        response = await self.nearby(lat=50.98, lng=11.03)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "60")
        self.assertIn("try again", response.json()["detail"])
        self.assertEqual(len(self.requests), 1)
        self.now += 61
        response = await self.nearby(lat=50.98, lng=11.03)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(len(self.requests), 2)

    async def test_request_budget_is_atomic_across_database_connections(self):
        waits = await asyncio.gather(*[
            database.reserve_provider_request("tankerkoenig", self.now, 60) for _ in range(5)
        ])
        self.assertEqual(sorted(waits), [0, 60, 60, 60, 60])

    async def test_cache_and_request_budget_survive_reset_of_process_state(self):
        await self.nearby()
        german_search._refresh_lock = None
        self.assertEqual((await self.nearby()).status_code, 200)
        self.assertEqual((await self.nearby(lat=50.98, lng=11.03)).status_code, 503)
        self.assertEqual(len(self.requests), 1)

    async def test_freshness_is_area_based_and_expired_area_refreshes(self):
        await self.nearby()
        self.now += 901
        self.provider_stations[0]["e10"] = 1.999
        response = await self.nearby()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stations"][0]["price"]["pence_per_litre"], 199.9)
        self.assertEqual(len(self.requests), 2)

    async def test_outage_returns_bounded_stale_cache_with_a_visible_notice(self):
        await self.nearby()
        self.now += 901
        self.timeout = True
        response = await self.nearby()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 1)
        self.assertIn("cached prices", response.json()["notice"])
        self.now += 3600
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("test-private-key", response.text)

    async def test_outage_without_cache_is_not_reported_as_no_stations(self):
        self.timeout = True
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertIn("refresh", response.json()["detail"])
        self.assertIn("Retry-After", response.headers)
        self.assertIsNone(await database.get_german_area("52.38,9.73"))

    async def test_missing_key_is_unavailable_without_a_network_request(self):
        self.settings.tankerkoenig_api_key = ""
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.requests, [])

    async def test_provider_backoff_is_respected(self):
        self.response_override = httpx.Response(429, headers={"Retry-After": "120"})
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "120")
        self.now += 61
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "59")
        self.assertEqual(len(self.requests), 1)

    async def test_provider_error_body_is_not_cached_or_exposed(self):
        self.response_override = httpx.Response(200, json={"ok": False, "message": "test-private-key"})
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("test-private-key", response.text)
        self.assertIsNone(await database.get_german_area("52.38,9.73"))

    async def test_malformed_station_does_not_create_a_partial_area_cache(self):
        self.response_override = httpx.Response(200, json={"ok": True, "stations": [
            self.provider_stations[0], {"id": "broken"},
        ]})
        response = await self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(await database.get_german_area("52.38,9.73"))
        self.assertIsNone(await database.get_station("de_hanover"))

    async def test_closed_station_refresh_removes_previously_cached_prices(self):
        await self.nearby()
        self.now += 901
        self.provider_stations[0]["isOpen"] = False
        response = await self.nearby()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        self.assertEqual(await database.get_station_prices("de_hanover"), [])

    async def test_missing_fuel_does_not_keep_old_prices(self):
        await self.nearby()
        self.now += 901
        self.provider_stations[0]["e5"] = False
        response = await self.nearby(fuel_type="E5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        self.assertNotIn("E5", [p["fuel_type"] for p in await database.get_station_prices("de_hanover")])

    async def test_old_fixed_city_prices_are_not_used_for_nearby_results(self):
        old_station = tankerkoenig_client._normalise_station({
            **self.provider_stations[0], "id": "old-cheapest", "e10": 1.01,
        }, "2026-01-01T00:00:00Z")
        await database.bulk_upsert_stations([old_station])
        await database.bulk_upsert_prices(old_station["prices"])
        response = await self.nearby()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["cheapest"]["station_id"], "de_hanover")

    async def test_large_radius_reports_the_actual_fetched_coverage(self):
        response = await self.nearby(radius=50)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(response.json()["radius_miles"] * KM_PER_MILE, 25)
        self.assertIn("within", response.json()["notice"])

    async def test_uk_and_western_netherlands_do_not_call_german_provider(self):
        for lat, lng in ((51.5074, -0.1278), (52.3676, 4.9041)):
            response = await self.nearby(lat=lat, lng=lng)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.requests, [])

    async def test_invalid_coordinates_are_rejected_before_provider_calls(self):
        for lat, lng in ((91, 9), (52, 181), ("nan", 9)):
            response = await self.nearby(lat=lat, lng=lng)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_dutch_border_results_remain_available_during_german_outage(self):
        station = {
            "station_id": "nl_venlo", "trading_name": "Venlo", "country": "nl",
            "address": "Test", "postcode": "5911", "latitude": 51.37, "longitude": 6.17,
        }
        station["prices"] = [{
            "station_id": "nl_venlo", "fuel_type": "E10", "pence_per_litre": 205.0,
            "updated_at": "2026-10-02T13:42:26Z",
        }]
        self.dutch_stations = [station]
        self.timeout = True
        response = await self.nearby(lat=51.37, lng=6.17)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["stations"][0]["country"], "nl")
        self.assertIn("Dutch stations only", response.json()["notice"])

    async def test_invalidated_empty_cache_is_not_used_to_hide_a_provider_outage(self):
        self.provider_stations = []
        self.assertEqual((await self.nearby()).status_code, 200)
        self.now += 901
        self.timeout = True
        self.assertEqual((await self.nearby()).status_code, 503)


if __name__ == "__main__":
    unittest.main()
