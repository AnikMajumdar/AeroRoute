"""A custom aircraft profile may only be used by the user who created it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.fakes import make_aircraft, make_airport


class _StopCalculation(Exception):
    pass


@pytest.fixture
def calculation(api, monkeypatch):
    """Two eligible airports, plus a recorder replacing the (network-bound) route calculator."""
    dep, dest = make_airport("KJFK"), make_airport("KLAX")
    api.db.tables["airports"] = [dep, dest]
    seen: dict = {}

    async def fake_calculate(**kwargs):
        seen.update(kwargs)
        raise _StopCalculation

    monkeypatch.setattr("app.routers.routes.route_calculator.calculate", fake_calculate)

    def request(aircraft_id: str):
        return api.client.post(
            "/routes/calculate",
            json={
                "departure_airport_id": dep["id"],
                "destination_airport_id": dest["id"],
                "aircraft_profile_id": aircraft_id,
                "departure_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                "fuel_price_usd_per_gal": 6.5,
            },
        )

    return request, seen


def test_user_cannot_use_another_users_custom_aircraft(api, calculation):
    request, seen = calculation
    other = make_aircraft(user_id="user_B", is_preset=False, name="B's Bonanza")
    api.db.tables["aircraft_profiles"] = [other]
    response = request(other["id"])
    assert response.status_code == 404
    assert response.json()["detail"] == "Aircraft profile not found"
    assert not seen, "the calculator must not run for an aircraft the user does not own"
    assert api.db.rows("route_requests") == [], "no route request may be created either"


def test_user_can_use_own_custom_aircraft(api, calculation):
    request, seen = calculation
    mine = make_aircraft(user_id="user_A", is_preset=False, name="My Mooney")
    api.db.tables["aircraft_profiles"] = [mine]
    request(mine["id"])
    assert seen["aircraft"]["id"] == mine["id"]


def test_any_user_can_use_a_preset(api, calculation):
    request, seen = calculation
    preset = make_aircraft(user_id=None, is_preset=True)
    api.db.tables["aircraft_profiles"] = [preset]
    request(preset["id"])
    assert seen["aircraft"]["id"] == preset["id"]


def test_unknown_aircraft_is_404(api, calculation):
    request, seen = calculation
    response = request("00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert not seen
