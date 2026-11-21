"""Range feasibility: a flight the aircraft cannot fly non-stop must be flagged, and capacity must be configurable."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.data.aircraft_presets import AIRCRAFT_PRESETS
from app.services.fuel_model import calculate_fuel_breakdown, still_air_range_nm, usable_fuel_capacity
from app.services.route_calculator import route_calculator
from tests.fakes import calculation_env, install_pressure_winds, make_aircraft, make_airport

KJFK = make_airport("KJFK")
KBOS = make_airport("KBOS", latitude=42.3643, longitude=-71.0052)
KORD = make_airport("KORD", latitude=41.9786, longitude=-87.9048)
KLAX = make_airport("KLAX", latitude=33.9425, longitude=-118.4081)


def _preset(name: str) -> dict:
    spec = next(spec for spec in AIRCRAFT_PRESETS if spec["name"] == name)
    return make_aircraft(**{key: value for key, value in spec.items() if key != "notes"})


async def _calculate(aircraft: dict, departure: dict, destination: dict) -> dict:
    return await route_calculator.calculate(
        departure,
        destination,
        aircraft,
        6.5,
        supabase=None,
        checkpoint_candidates=[],
        departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
    )


class TestFuelModel:
    CESSNA = {"fuel_burn_gph": 8.5, "cruise_speed_kt": 122, "climb_fuel_gal": 1.5, "reserve_fuel_min": 45, "usable_fuel_gal": 53}

    def test_a_flight_within_capacity_is_feasible(self):
        breakdown = calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=120)
        assert breakdown.feasible is True
        assert breakdown.fuel_remaining_gal == pytest.approx(53 - breakdown.total_required_gal, abs=0.01)
        assert breakdown.warnings == []

    def test_a_flight_beyond_capacity_is_flagged_with_the_range(self):
        # KJFK-KLAX in a 172: about 17.9 h of cruise (used to be returned without any warning)
        breakdown = calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=17.9 * 60)
        assert breakdown.feasible is False
        assert breakdown.fuel_remaining_gal < 0
        (warning,) = breakdown.warnings
        expected_range = (53 - 1.5 - 45 / 60 * 8.5) / 8.5 * 122
        assert breakdown.still_air_range_nm == pytest.approx(expected_range, abs=0.1)
        assert "Not feasible non-stop" in warning
        assert f"{expected_range:.0f} NM" in warning
        assert "53 gal usable" in warning

    def test_exactly_enough_fuel_is_feasible(self):
        needed = calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=100).total_required_gal
        breakdown = calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=100, usable_fuel_gal=needed)
        assert breakdown.feasible is True
        assert breakdown.fuel_remaining_gal == 0

    def test_unknown_capacity_is_reported_not_assumed(self):
        aircraft = {key: value for key, value in self.CESSNA.items() if key != "usable_fuel_gal"}
        breakdown = calculate_fuel_breakdown(aircraft, cruise_ete_minutes=17.9 * 60)
        assert breakdown.feasible is None
        assert breakdown.fuel_remaining_gal is None and breakdown.still_air_range_nm is None
        (warning,) = breakdown.warnings
        assert "not set" in warning and "not checked" in warning

    def test_explicit_capacity_overrides_the_profile(self):
        assert calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=120, usable_fuel_gal=10).feasible is False

    @pytest.mark.parametrize(("value", "expected"), [(53, 53.0), ("48.5", 48.5), (0, None), (None, None)])
    def test_usable_fuel_capacity(self, value, expected):
        assert usable_fuel_capacity({"usable_fuel_gal": value}) == expected

    def test_no_range_without_usable_fuel_beyond_reserve(self):
        assert still_air_range_nm(self.CESSNA, usable_fuel_gal=5) == 0

    @pytest.mark.parametrize("spec", AIRCRAFT_PRESETS, ids=lambda s: s["name"])
    def test_every_preset_has_a_plausible_capacity(self, spec):
        aircraft = _preset(spec["name"])
        endurance_h = spec["usable_fuel_gal"] / spec["fuel_burn_gph"]
        assert 3.5 <= endurance_h <= 7, "typical piston/turboprop endurance"
        assert 300 <= still_air_range_nm(aircraft, spec["usable_fuel_gal"]) <= endurance_h * spec["cruise_speed_kt"]


class TestCalculatedRoutes:
    @pytest.fixture(autouse=True)
    def _winds(self, monkeypatch):
        install_pressure_winds(monkeypatch)

    async def test_transcontinental_flight_in_a_cessna_is_not_feasible(self):
        result = await _calculate(_preset("Cessna 172"), KJFK, KLAX)
        assert result["primary"].fuel_breakdown["feasible"] is False
        assert any("Not feasible non-stop" in w for w in result["warnings"])

    async def test_short_flight_in_a_cessna_is_feasible_and_silent(self):
        result = await _calculate(_preset("Cessna 172"), KJFK, KBOS)
        assert result["primary"].fuel_breakdown["feasible"] is True
        assert result["primary"].fuel_breakdown["fuel_remaining_gal"] > 0
        assert not any("Not feasible" in w for w in result["warnings"])

    async def test_a_turboprop_also_cannot_cross_the_country_non_stop(self):
        result = await _calculate(_preset("King Air 350"), KJFK, KLAX)
        assert result["primary"].fuel_breakdown["feasible"] is False

    async def test_a_twin_can_fly_to_chicago(self):
        result = await _calculate(_preset("Beechcraft Baron"), KJFK, KORD)
        assert result["primary"].fuel_breakdown["feasible"] is True

    async def test_custom_aircraft_without_capacity_gets_a_note(self):
        aircraft = make_aircraft(is_preset=False, user_id="user_A")
        result = await _calculate(aircraft, KJFK, KLAX)
        assert result["primary"].fuel_breakdown["feasible"] is None
        assert any("capacity is not set" in w for w in result["warnings"])


class TestApi:
    def test_calculate_response_and_get_report_the_infeasible_plan(self, api, monkeypatch):
        env = calculation_env(api, monkeypatch)
        env.db.rows("aircraft_profiles")[0]["usable_fuel_gal"] = 53.0
        created = env.post().json()
        fetched = env.client.get(f"/routes/{created['id']}").json()
        for body in (created, fetched):
            assert body["fuel_breakdown"]["feasible"] is False
            assert body["fuel_breakdown"]["usable_capacity_gal"] == 53.0
            assert body["fuel_breakdown"]["still_air_range_nm"] > 0
            assert any("Not feasible non-stop" in w for w in body["warnings"])

    def test_aircraft_profile_exposes_the_capacity(self, api, monkeypatch):
        env = calculation_env(api, monkeypatch)
        env.db.rows("aircraft_profiles")[0]["usable_fuel_gal"] = 53.0
        body = env.post().json()
        assert body["aircraft_profile"]["usable_fuel_gal"] == 53.0

    def test_custom_aircraft_can_be_created_with_a_capacity(self, api):
        response = api.client.post(
            "/aircraft", json={"name": "My RV-10", "cruise_speed_kt": 160, "fuel_burn_gph": 13, "usable_fuel_gal": 60}
        )
        assert response.status_code == 201
        assert response.json()["usable_fuel_gal"] == 60
        assert api.db.rows("aircraft_profiles")[0]["usable_fuel_gal"] == 60

    def test_capacity_is_optional(self, api):
        response = api.client.post("/aircraft", json={"name": "My RV-10", "cruise_speed_kt": 160, "fuel_burn_gph": 13})
        assert response.status_code == 201
        assert response.json()["usable_fuel_gal"] is None

    @pytest.mark.parametrize("capacity", [0, -5, 2001, "lots"])
    def test_invalid_capacity_is_rejected(self, api, capacity):
        response = api.client.post(
            "/aircraft", json={"name": "My RV-10", "cruise_speed_kt": 160, "fuel_burn_gph": 13, "usable_fuel_gal": capacity}
        )
        assert response.status_code == 422
        assert api.db.rows("aircraft_profiles") == []
