"""Climb and descent cover part of the route: they must not be added on top of a full-distance cruise."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.data.aircraft_presets import AIRCRAFT_PRESETS
from app.geo.utils import haversine_nm
from app.services.fuel_model import calculate_fuel_breakdown
from app.services.route_calculator import (
    CLIMB_SPEED_FACTOR,
    DESCENT_SPEED_FACTOR,
    plan_phases,
    route_calculator,
    split_leg_distances,
)
from tests.fakes import install_pressure_winds, make_aircraft, make_airport

KJFK = make_airport("KJFK")
KBOS = make_airport("KBOS", latitude=42.3643, longitude=-71.0052)
KORD = make_airport("KORD", latitude=41.9786, longitude=-87.9048)
NEARBY = make_airport("KNRB", latitude=40.9731, longitude=-73.7789)  # about 20 NM north of KJFK


def _aircraft(name: str = "Cessna 172") -> dict:
    spec = next(spec for spec in AIRCRAFT_PRESETS if spec["name"] == name)
    return make_aircraft(**{key: value for key, value in spec.items() if key != "notes"})


def _distance(a: dict, b: dict) -> float:
    return haversine_nm(a["latitude"], a["longitude"], b["latitude"], b["longitude"])


async def _variants(aircraft: dict, departure: dict, destination: dict) -> dict:
    result = await route_calculator.calculate(
        departure,
        destination,
        aircraft,
        6.5,
        supabase=None,
        checkpoint_candidates=[],
        departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    return {variant.name: variant for variant in result["variants"]}


class TestPlanPhases:
    CESSNA = {"cruise_speed_kt": 122, "climb_time_min": 12, "descent_time_min": 8}

    def test_distance_covered_while_climbing_and_descending(self):
        phases = plan_phases(500, self.CESSNA)
        assert phases.climb_minutes == 12 and phases.descent_minutes == 8
        assert phases.climb_nm == pytest.approx(12 / 60 * 122 * CLIMB_SPEED_FACTOR)
        assert phases.descent_nm == pytest.approx(8 / 60 * 122 * DESCENT_SPEED_FACTOR)

    def test_a_route_too_short_to_reach_cruise_scales_both_phases(self):
        phases = plan_phases(20, self.CESSNA)
        assert phases.climb_nm + phases.descent_nm == pytest.approx(20)
        scale = 20 / (12 / 60 * 122 * CLIMB_SPEED_FACTOR + 8 / 60 * 122 * DESCENT_SPEED_FACTOR)
        assert phases.climb_minutes == pytest.approx(12 * scale)
        assert phases.descent_minutes == pytest.approx(8 * scale)

    def test_defaults_apply_when_the_profile_has_no_phase_times(self):
        phases = plan_phases(500, {"cruise_speed_kt": 100})
        assert (phases.climb_minutes, phases.descent_minutes) == (12, 8)

    def test_minutes_for_a_share_of_the_phase(self):
        phases = plan_phases(500, self.CESSNA)
        assert phases.climb_minutes_for(phases.climb_nm / 2) == pytest.approx(6)
        assert phases.descent_minutes_for(phases.descent_nm) == pytest.approx(8)
        assert plan_phases(500, {**self.CESSNA, "climb_time_min": 0}).climb_minutes_for(0) == 0


class TestSplitLegDistances:
    def test_single_leg(self):
        assert split_leg_distances([100.0], 17.0, 15.0) == [(17.0, 68.0, 15.0)]

    def test_climb_and_descent_span_several_legs(self):
        assert split_leg_distances([10.0, 30.0, 10.0], 25.0, 12.0) == [(10.0, 0.0, 0.0), (15.0, 13.0, 2.0), (0.0, 0.0, 10.0)]

    def test_no_phases(self):
        assert split_leg_distances([10.0, 20.0], 0.0, 0.0) == [(0.0, 10.0, 0.0), (0.0, 20.0, 0.0)]

    @pytest.mark.parametrize("legs", [[100.0], [60.0, 40.0], [5.0, 50.0, 5.0, 40.0]])
    def test_every_leg_adds_up(self, legs):
        total = sum(legs)
        phases = plan_phases(total, {"cruise_speed_kt": 122, "climb_time_min": 12, "descent_time_min": 8})
        parts = split_leg_distances(legs, phases.climb_nm, phases.descent_nm)
        for leg, (climb, cruise, descent) in zip(legs, parts):
            assert climb + cruise + descent == pytest.approx(leg)
            assert min(climb, cruise, descent) >= 0
        assert sum(p[0] for p in parts) == pytest.approx(phases.climb_nm)
        assert sum(p[2] for p in parts) == pytest.approx(phases.descent_nm)


class TestFuelForShortenedPhases:
    CESSNA = {"fuel_burn_gph": 8.5, "climb_fuel_gal": 1.5, "climb_time_min": 12, "descent_time_min": 8, "reserve_fuel_min": 45}

    def test_a_shortened_climb_burns_proportionally_less(self):
        breakdown = calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=0, climb_ete_minutes=6, descent_ete_minutes=4)
        assert breakdown.climb_fuel_gal == pytest.approx(0.75)
        assert breakdown.descent_fuel_gal == pytest.approx(4 / 60 * 8.5 * 0.6)

    def test_a_full_climb_keeps_the_profile_fuel(self):
        assert calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=60, climb_ete_minutes=12).climb_fuel_gal == 1.5
        assert calculate_fuel_breakdown(self.CESSNA, cruise_ete_minutes=60).climb_fuel_gal == 1.5


class TestCalculatedEte:
    async def test_still_air_ete_does_not_count_the_climb_and_descent_distance_twice(self, monkeypatch):
        install_pressure_winds(monkeypatch)
        direct = (await _variants(_aircraft(), KJFK, KBOS))["direct"]
        distance = _distance(KJFK, KBOS)
        covered = 12 / 60 * 122 * CLIMB_SPEED_FACTOR + 8 / 60 * 122 * DESCENT_SPEED_FACTOR
        assert direct.ete_minutes == pytest.approx(20 + (distance - covered) / 122 * 60, abs=0.05)
        old_ete = 20 + distance / 122 * 60
        assert old_ete - direct.ete_minutes == pytest.approx(covered / 122 * 60, abs=0.05)  # about 15.6 min

    async def test_a_headwind_only_slows_the_cruise_portion(self, monkeypatch):
        install_pressure_winds(monkeypatch, headwind_kt=30)
        direct = (await _variants(_aircraft(), KJFK, KORD))["direct"]
        distance = _distance(KJFK, KORD)
        covered = 12 / 60 * 122 * CLIMB_SPEED_FACTOR + 8 / 60 * 122 * DESCENT_SPEED_FACTOR
        assert direct.ete_minutes == pytest.approx(20 + (distance - covered) / (122 - 30) * 60, abs=0.05)

    async def test_a_tailwind_speeds_up_the_cruise_portion(self, monkeypatch):
        install_pressure_winds(monkeypatch, headwind_kt=-30)
        direct = (await _variants(_aircraft(), KJFK, KORD))["direct"]
        covered = 12 / 60 * 122 * CLIMB_SPEED_FACTOR + 8 / 60 * 122 * DESCENT_SPEED_FACTOR
        assert direct.ete_minutes == pytest.approx(20 + (_distance(KJFK, KORD) - covered) / (122 + 30) * 60, abs=0.05)

    async def test_segments_add_up_to_the_route(self, monkeypatch):
        install_pressure_winds(monkeypatch)
        variants = await _variants(_aircraft(), KJFK, KORD)
        for variant in variants.values():
            assert sum(s["ete_minutes"] for s in variant.segments) == pytest.approx(variant.ete_minutes, abs=0.05)
            assert sum(s["distance_nm"] for s in variant.segments) == pytest.approx(variant.distance_nm, abs=0.05)

    async def test_segment_groundspeed_is_the_leg_average(self, monkeypatch):
        install_pressure_winds(monkeypatch)
        direct = (await _variants(_aircraft(), KJFK, KORD))["direct"]
        (segment,) = direct.segments
        assert segment["groundspeed_kt"] == pytest.approx(segment["distance_nm"] / segment["ete_minutes"] * 60, abs=0.1)
        assert segment["groundspeed_kt"] < 122  # the climb is slower than cruise

    async def test_scoring_baseline_uses_the_same_model(self, monkeypatch):
        install_pressure_winds(monkeypatch)
        variants = await _variants(_aircraft(), KJFK, KORD)
        direct, left = variants["direct"], variants["left_offset"]
        assert direct.score_breakdown["component_scores"]["time"] == 100.0
        expected = 100 - (left.ete_minutes / direct.ete_minutes - 1) * 80
        assert left.score_breakdown["component_scores"]["time"] == pytest.approx(expected, abs=0.1)

    async def test_a_hop_too_short_to_reach_cruise_has_no_cruise_phase(self, monkeypatch):
        install_pressure_winds(monkeypatch)
        direct = (await _variants(_aircraft(), KJFK, NEARBY))["direct"]
        distance = _distance(KJFK, NEARBY)
        scale = distance / (12 / 60 * 122 * CLIMB_SPEED_FACTOR + 8 / 60 * 122 * DESCENT_SPEED_FACTOR)
        assert scale < 1
        assert direct.ete_minutes == pytest.approx(20 * scale, abs=0.05)
        assert direct.fuel_breakdown["cruise_fuel_gal"] == 0
        assert direct.fuel_breakdown["climb_fuel_gal"] == pytest.approx(1.5 * scale, abs=0.01)

    @pytest.mark.parametrize("name", [spec["name"] for spec in AIRCRAFT_PRESETS])
    async def test_every_preset_flies_faster_than_the_old_estimate(self, monkeypatch, name):
        install_pressure_winds(monkeypatch)
        aircraft = _aircraft(name)
        direct = (await _variants(aircraft, KJFK, KORD))["direct"]
        old_ete = _distance(KJFK, KORD) / aircraft["cruise_speed_kt"] * 60 + aircraft["climb_time_min"] + aircraft["descent_time_min"]
        assert 0 < direct.ete_minutes < old_ete
