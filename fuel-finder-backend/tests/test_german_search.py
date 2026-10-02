"""Regression checks using a temporary cache and no external API requests."""

import tempfile
import unittest
from time import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app import database
from app.main import app
from app.services import german_search, tankerkoenig_client
from app.services.country_detector import in_country_box
from app.services.geo import KM_PER_MILE, haversine_miles


class GermanSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(directory.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        await database.init_db()
        settings_patch = patch.object(german_search, "get_settings", return_value=SimpleNamespace(
            tankerkoenig_api_key="test-key", price_cache_ttl=900, tankerkoenig_stale_ttl=3600,
        ))
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        upstream_patch = patch.object(german_search, "fetch_stations_de", new=AsyncMock(return_value=[]))
        self.fetch = upstream_patch.start()
        self.addCleanup(upstream_patch.stop)
        lock_patch = patch.object(german_search, "_refresh_lock", None)
        lock_patch.start()
        self.addCleanup(lock_patch.stop)

        locations = [
            ("de_duesseldorf", "de", 51.2277, 6.7735, 180.0),
            ("de_cologne", "de", 50.94, 6.96, 175.0),
            ("de_berlin", "de", 52.52, 13.40, 181.0),
            ("de_border", "de", 51.37, 6.25, 190.0),
            ("nl_venlo", "nl", 51.37, 6.17, 205.0),
            ("nl_amsterdam", "nl", 52.3676, 4.9041, 210.0),
            ("uk_london", "uk", 51.5074, -0.1278, 155.0),
        ]
        await database.bulk_upsert_stations([
            {
                "station_id": station_id,
                "trading_name": station_id,
                "address": "Test station",
                "postcode": "12345",
                "latitude": lat,
                "longitude": lng,
                "country": country,
            }
            for station_id, country, lat, lng, _ in locations
        ])
        await database.bulk_upsert_prices([
            {
                "station_id": station_id,
                "fuel_type": fuel_type,
                "pence_per_litre": price,
                "updated_at": "2026-10-02T13:42:26.358727Z",
            }
            for station_id, _, _, _, price in locations
            for fuel_type in ("E10", "E5", "B7")
        ])
        german_stations = []
        for station_id, country, _, _, _ in locations:
            if country == "de":
                station = await database.get_station(station_id)
                station["amenities"] = []
                station["prices"] = await database.get_station_prices(station_id)
                german_stations.append(station)
        for _, _, lat, lng, _ in locations:
            if in_country_box(lat, lng, "de"):
                key, area_lat, area_lng = german_search.area_coordinates(lat, lng)
                await database.store_german_area(key, [
                    s for s in german_stations
                    if haversine_miles(area_lat, area_lng, s["latitude"], s["longitude"]) * KM_PER_MILE <= 25
                ], time(), 3600)
        # ASGITransport does not run lifespan, so no ingestion jobs are started.
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_western_german_cities_find_cached_prices_for_all_fuels(self):
        for station_id, lat, lng in (
            ("de_duesseldorf", 51.2277, 6.7735),
            ("de_cologne", 50.94, 6.96),
        ):
            for fuel_type in ("E10", "E5", "B7"):
                with self.subTest(city=station_id, fuel_type=fuel_type):
                    response = await self.client.get("/api/stations/nearby", params={
                        "lat": lat, "lng": lng, "fuel_type": fuel_type,
                    })
                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body["total"], 1)
                    self.assertEqual(body["stations"][0]["station_id"], station_id)
                    self.assertEqual(body["stations"][0]["price"]["currency"], "EUR")

    async def test_border_search_compares_both_euro_providers_before_limiting(self):
        response = await self.client.get("/api/stations/nearby", params={
            "lat": 51.37, "lng": 6.17, "radius": 10, "limit": 1,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["stations"]), 1)
        self.assertEqual(body["cheapest"]["station_id"], "de_border")
        self.assertEqual(body["nearest"]["station_id"], "nl_venlo")

    async def test_distance_sort_works_across_the_border(self):
        response = await self.client.get("/api/stations/nearby", params={
            "lat": 51.37, "lng": 6.17, "radius": 10, "sort": "distance",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [s["station_id"] for s in response.json()["stations"]],
            ["nl_venlo", "de_border"],
        )

    async def test_existing_country_searches_and_ios_route_still_work(self):
        for station_id, lat, lng, currency in (
            ("de_berlin", 52.52, 13.40, "EUR"),
            ("nl_amsterdam", 52.3676, 4.9041, "EUR"),
            ("uk_london", 51.5074, -0.1278, "GBP"),
        ):
            with self.subTest(station_id=station_id):
                response = await self.client.get("/stations/nearby", params={
                    "lat": lat, "lng": lng,
                })
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["total"], 1)
                self.assertEqual(body["stations"][0]["station_id"], station_id)
                self.assertEqual(body["stations"][0]["price"]["currency"], currency)

    async def test_fill_recommendation_uses_cents_for_euro_prices(self):
        response = await self.client.get("/api/recommendation/fill-now", params={
            "lat": 51.37, "lng": 6.17,
        })
        self.assertEqual(response.status_code, 200)
        recommendation = response.json()["recommendation"]
        self.assertEqual(recommendation["recommended_station_id"], "de_border")
        self.assertIn("c/L", recommendation["explanation"])
        self.assertNotIn("p/L", recommendation["explanation"])

    async def test_uk_recommendation_keeps_pence(self):
        response = await self.client.get("/api/recommendation/fill-now", params={
            "lat": 51.5074, "lng": -0.1278,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("p/L", response.json()["recommendation"]["explanation"])

    async def test_successful_empty_provider_response_returns_an_empty_result(self):
        response = await self.client.get("/api/stations/nearby", params={
            "lat": 52.3759, "lng": 9.7320,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stations"], [])
        self.assertIsNone(response.json()["cheapest"])
        self.fetch.assert_awaited_once_with(52.38, 9.73)


class TankerkoenigRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_uses_the_documented_maximum_radius(self):
        requests = []

        def handler(request):
            requests.append(request)
            if float(request.url.params["rad"]) > 25:
                return httpx.Response(200, json={"ok": False, "message": "invalid radius"})
            return httpx.Response(200, json={"ok": True, "stations": [{
                "id": "test-berlin", "name": "Berlin", "lat": 52.52, "lng": 13.40,
                "postCode": 10115, "e10": 1.819, "e5": False, "diesel": 1.729,
            }]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(tankerkoenig_client, "get_settings", return_value=SimpleNamespace(
            tankerkoenig_api_key="test-key",
        )), patch.object(tankerkoenig_client.httpx, "AsyncClient", return_value=client):
            stations = await tankerkoenig_client.fetch_stations_de(52.52, 13.40)

        self.assertEqual(len(requests), 1)
        self.assertTrue(all(float(r.url.params["rad"]) <= 25 for r in requests))
        self.assertEqual(len(stations), 1)  # Duplicate stations across searches are merged.
        self.assertEqual(stations[0]["station_id"], "de_test-berlin")
        self.assertEqual(stations[0]["prices"][0]["pence_per_litre"], 181.9)


if __name__ == "__main__":
    unittest.main()
