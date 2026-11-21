"""Groundspeed must account for the wind correction angle: crabbing into a crosswind costs speed along the track."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.data.aircraft_presets import AIRCRAFT_PRESETS
from app.geo.utils import haversine_nm
from app.services.open_meteo import OpenMeteoClient
from app.services.route_calculator import (
    CLIMB_SPEED_FACTOR,
    DESCENT_SPEED_FACTOR,
    MIN_GROUNDSPEED_FRACTION,
    route_calculator,
)
from app.services.wind_altitude import crosswind_component_kt, groundspeed_kt, wind_components_kt
from tests.fakes import install_pressure_winds, make_aircraft, make_airport

KJFK = make_airport("KJFK")
KORD = make_airport("KORD", latitude=41.9786, longitude=-87.9048)


def _cessna() -> dict:
    spec = next(spec for spec in AIRCRAFT_PRESETS if spec["name"] == "Cessna 172")
    return make_aircraft(**{key: value for key, value in spec.items() if key != "notes"})


async def _calculate(aircraft: dict) -> dict:
    return await route_calculator.calculate(
        KJFK,
        KORD,
        aircraft,
        6.5,
        supabase=None,
        checkpoint_candidates=[],
        departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
    )


def _cruise_nm() -> float:
    distance = haversine_nm(KJFK["latitude"], KJFK["longitude"], KORD["latitude"], KORD["longitude"])
    return distance - 12 / 60 * 122 * CLIMB_SPEED_FACTOR - 8 / 60 * 122 * DESCENT_SPEED_FACTOR


class TestCrosswindComponent:
    @pytest.mark.parametrize(
        ("speed", "wind_from", "track", "expected"),
        [
            (20, 90, 0, 20),  # wind from the east, flying north: pure crosswind
            (20, 270, 0, 20),  # from the west: same magnitude
            (20, 0, 0, 0),  # pure headwind
            (20, 180, 0, 0),  # pure tailwind
            (20, 45, 0, 20 * math.sin(math.radians(45))),
            (0, 123, 77, 0),
        ],
    )
    def test_crosswind_magnitude(self, speed, wind_from, track, expected):
        assert crosswind_component_kt(speed, wind_from, track) == pytest.approx(expected, abs=1e-9)

    @pytest.mark.parametrize("track", [0, 33, 90, 217, 359])
    def test_components_recombine_to_the_wind_speed(self, track):
        signed, _, _ = wind_components_kt(30, 135, track)
        crosswind = crosswind_component_kt(30, 135, track)
        assert math.hypot(signed, crosswind) == pytest.approx(30)


class TestGroundspeed:
    def test_calm_air(self):
        assert groundspeed_kt(120, 0, 0) == 120

    def test_headwind_and_tailwind_subtract_and_add(self):
        assert groundspeed_kt(120, 30) == 90
        assert groundspeed_kt(120, -30) == 150

    def test_a_crosswind_alone_costs_speed(self):
        assert groundspeed_kt(120, 0, 40) == pytest.approx(math.sqrt(120**2 - 40**2))  # 113.1 kt, not 120

    def test_crosswind_and_headwind_combine(self):
        assert groundspeed_kt(120, 20, 30) == pytest.approx(math.sqrt(120**2 - 30**2) - 20)

    def test_the_sign_of_the_crosswind_does_not_matter(self):
        assert groundspeed_kt(120, 10, -35) == groundspeed_kt(120, 10, 35)

    @pytest.mark.parametrize("crosswind", [120, 150])
    def test_a_crosswind_the_aircraft_cannot_crab_into_gives_no_progress(self, crosswind):
        assert groundspeed_kt(120, 0, crosswind) == 0

    def test_matches_the_wind_triangle(self):
        # wind from 90 deg at 40 kt, track 0 deg: crab angle asin(40/120), groundspeed 120 * cos(crab angle)
        crab = math.asin(40 / 120)
        assert groundspeed_kt(120, 0, crosswind_component_kt(40, 90, 0)) == pytest.approx(120 * math.cos(crab))


class TestSampledLegs:
    async def test_each_sampled_leg_reports_its_crosswind(self, monkeypatch):
        client = OpenMeteoClient()

        async def wind(lat, lon, cruise_altitude_ft=10000, forecast_time=None):
            return {"wind_speed_kt": 20.0, "wind_direction_deg": 90.0, "wind_source": "pressure_level"}

        monkeypatch.setattr(client, "get_wind_at_point", wind)
        segments, _ = await client.sample_route_winds([(40.0, -100.0), (41.0, -100.0)])  # flying north
        (segment,) = segments
        assert segment["crosswind_component_kt"] == pytest.approx(20.0, abs=0.01)
        assert segment["headwind_component_kt"] == pytest.approx(0.0, abs=0.01)

    async def test_legs_without_wind_have_no_crosswind(self, monkeypatch):
        client = OpenMeteoClient()

        async def no_wind(lat, lon, cruise_altitude_ft=10000, forecast_time=None):
            return None

        monkeypatch.setattr(client, "get_wind_at_point", no_wind)
        segments, _ = await client.sample_route_winds([(40.0, -100.0), (41.0, -100.0)])
        (segment,) = segments
        assert segment["crosswind_component_kt"] is None


class TestCalculatedEte:
    async def test_a_crosswind_lengthens_the_cruise(self, monkeypatch):
        install_pressure_winds(monkeypatch, crosswind_kt=40)
        direct = next(v for v in (await _calculate(_cessna()))["variants"] if v.name == "direct")
        expected = 20 + _cruise_nm() / math.sqrt(122**2 - 40**2) * 60
        assert direct.ete_minutes == pytest.approx(expected, abs=0.05)
        calm = 20 + _cruise_nm() / 122 * 60
        assert direct.ete_minutes > calm + 10  # about 5% slower than calm air on a 640 NM trip

    async def test_headwind_and_crosswind_combine(self, monkeypatch):
        install_pressure_winds(monkeypatch, headwind_kt=20, crosswind_kt=30)
        direct = next(v for v in (await _calculate(_cessna()))["variants"] if v.name == "direct")
        expected = 20 + _cruise_nm() / (math.sqrt(122**2 - 30**2) - 20) * 60
        assert direct.ete_minutes == pytest.approx(expected, abs=0.05)

    async def test_calm_air_is_unchanged(self, monkeypatch):
        install_pressure_winds(monkeypatch)
        direct = next(v for v in (await _calculate(_cessna()))["variants"] if v.name == "direct")
        assert direct.ete_minutes == pytest.approx(20 + _cruise_nm() / 122 * 60, abs=0.05)
        assert direct.slow_legs == 0

    async def test_the_planning_floor_scales_with_the_aircraft(self, monkeypatch):
        # a 110 kt headwind leaves a Cessna 12 kt; the floor is 25% of 122 kt (it used to be a fixed 60 kt)
        install_pressure_winds(monkeypatch, headwind_kt=110)
        result = await _calculate(_cessna())
        direct = next(v for v in result["variants"] if v.name == "direct")
        floor = MIN_GROUNDSPEED_FRACTION * 122
        assert direct.ete_minutes == pytest.approx(20 + _cruise_nm() / floor * 60, abs=0.05)
        assert direct.slow_legs == 1
        assert any("Very strong winds on" in w and "25% of cruise speed" in w for w in result["warnings"])

    async def test_a_crosswind_beyond_airspeed_is_floored_and_reported(self, monkeypatch):
        install_pressure_winds(monkeypatch, crosswind_kt=130)
        result = await _calculate(_cessna())
        assert result["primary"].slow_legs >= 1
        assert any("Very strong winds" in w for w in result["warnings"])

    async def test_moderate_winds_raise_no_floor_warning(self, monkeypatch):
        install_pressure_winds(monkeypatch, headwind_kt=25, crosswind_kt=25)
        result = await _calculate(_cessna())
        assert not any("Very strong winds" in w for w in result["warnings"])
