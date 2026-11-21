"""POST /routes/calculate must describe the route the same way GET /routes/{id} does."""

from __future__ import annotations

import pytest

from tests.fakes import calculation_env

SHARED_FIELDS = [
    "id",
    "route_request_id",
    "status",
    "route_preference",
    "fuel_price_usd_per_gal",
    "primary_distance_nm",
    "primary_ete_minutes",
    "primary_fuel_burn_gal",
    "primary_fuel_cost_usd",
    "primary_score",
    "wind_data_quality",
    "created_at",
]


@pytest.fixture
def env(api, monkeypatch):
    return calculation_env(api, monkeypatch)


class TestCalculateResponse:
    def test_echoes_the_requested_fuel_price(self, env):
        response = env.post()
        assert response.status_code == 201
        assert response.json()["fuel_price_usd_per_gal"] == 6.5  # used to be null

    @pytest.mark.parametrize("price", [0.01, 4.25, 50])
    def test_echoes_any_valid_price(self, env, price):
        env.payload["fuel_price_usd_per_gal"] = price
        assert env.post().json()["fuel_price_usd_per_gal"] == price

    def test_matches_the_stored_route_returned_by_get(self, env):
        created = env.post().json()
        fetched = env.client.get(f"/routes/{created['id']}").json()
        for field in SHARED_FIELDS:
            assert created[field] == fetched[field], field

    def test_fuel_cost_is_consistent_with_the_echoed_price(self, env):
        body = env.post().json()
        price = body["fuel_price_usd_per_gal"]
        tolerance = 0.005 * price + 0.01  # the breakdown's gallons are rounded to 0.01
        expected = body["fuel_breakdown"]["total_required_gal"] * price
        assert body["primary_fuel_cost_usd"] == pytest.approx(expected, abs=tolerance)
