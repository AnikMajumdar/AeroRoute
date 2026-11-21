"""Winds are sampled along every leg (great-circle midpoints, expected time over each point), not once per leg."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.geo.utils import destination_point, haversine_nm, initial_bearing_deg
from app.services import open_meteo
from app.services.open_meteo import (
    MAX_WIND_SAMPLES_PER_LEG,
    WIND_SAMPLE_SPACING_NM,
    OpenMeteoClient,
)
from app.services.route_calculator import CLIMB_SPEED_FACTOR, DESCENT_SPEED_FACTOR, route_calculator
from tests.fakes import make_aircraft, make_airport

KLAX = (33.9425, -118.4081)
KJFK = (40.6398, -73.7789)


def _wind(speed=10.0, direction=270.0, source="pressure_level"):
    return {
        "wind_speed_kt": speed,
        "wind_direction_deg": direction,
        "wind_altitude_ft": 10000,
        "wind_pressure_level_hpa": 700 if source == "pressure_level" else None,
        "wind_source": source,
    }


class Recorder:
    """Stands in for ``get_wind_at_point``: records every request and answers from a list (or a constant)."""

    def __init__(self, answers=None):
        self.answers = answers
        self.calls: list[tuple[float, float, datetime | None]] = []

    async def __call__(self, lat, lon, cruise_altitude_ft=10000, forecast_time=None):
        index = len(self.calls)
        self.calls.append((lat, lon, forecast_time))
        if callable(self.answers):
            return self.answers(index)
        if self.answers is None:
            return _wind()
        return self.answers[index]


def _client(monkeypatch, recorder: Recorder) -> OpenMeteoClient:
    client = OpenMeteoClient()
    monkeypatch.setattr(client, "get_wind_at_point", recorder)
    return client


def _north(distance_nm: float, start=(40.0, -100.0)):
    return [start, (start[0] + distance_nm / 60.0, start[1])]  # one degree of latitude is 60 NM


class TestSampleCount:
    @pytest.mark.parametrize(
        ("distance_nm", "expected"),
        [(10, 1), (120, 1), (190, 1), (210, 2), (290, 2), (410, 3), (640, 4), (2146, 11)],
    )
    async def test_one_sample_per_spacing(self, monkeypatch, distance_nm, expected):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds(_north(distance_nm))
        assert len(recorder.calls) == expected

    async def test_very_long_legs_are_capped(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds([(0.0, 0.0), (0.0, 120.0)])  # about 7,200 NM
        assert len(recorder.calls) == MAX_WIND_SAMPLES_PER_LEG

    async def test_the_spacing_is_a_parameter(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds(_north(290), spacing_nm=50)
        assert len(recorder.calls) == 6

    async def test_a_zero_length_leg_gets_one_sample(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds([(40.0, -100.0), (40.0, -100.0)])
        assert len(recorder.calls) == 1

    async def test_every_leg_is_sampled_separately(self, monkeypatch):
        recorder = Recorder()
        waypoints = [(40.0, -100.0), (42.0, -100.0), (42.0, -96.0)]  # about 120 NM, then about 178 NM
        segments, _ = await _client(monkeypatch, recorder).sample_route_winds(waypoints)
        assert len(segments) == 2
        assert [len(s["samples"]) for s in segments] == [1, 1]
        assert len(recorder.calls) == 2

    def test_the_default_spacing_is_documented(self):
        assert WIND_SAMPLE_SPACING_NM == 200.0


class TestSamplePositions:
    async def test_a_single_sample_is_the_great_circle_midpoint(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds([KLAX, KJFK], spacing_nm=100000)
        ((lat, lon, _),) = recorder.calls
        length = haversine_nm(*KLAX, *KJFK)
        expected = destination_point(*KLAX, initial_bearing_deg(*KLAX, *KJFK), length / 2)
        assert (lat, lon) == pytest.approx(expected, abs=1e-6)
        arithmetic_mean = ((KLAX[0] + KJFK[0]) / 2, (KLAX[1] + KJFK[1]) / 2)
        # the old arithmetic lat/lon mean is far from the real midpoint on a transcontinental leg
        assert haversine_nm(lat, lon, *arithmetic_mean) > 100

    async def test_samples_are_evenly_spaced_along_the_leg(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds([KLAX, KJFK])
        points = [(lat, lon) for lat, lon, _ in recorder.calls]
        length = haversine_nm(*KLAX, *KJFK)
        part = length / len(points)
        assert haversine_nm(*KLAX, *points[0]) == pytest.approx(part / 2, abs=0.5)
        for a, b in zip(points, points[1:]):
            assert haversine_nm(*a, *b) == pytest.approx(part, abs=0.5)
        assert haversine_nm(*points[-1], *KJFK) == pytest.approx(part / 2, abs=0.5)

    async def test_the_sample_ranges_cover_the_leg_without_gaps(self, monkeypatch):
        segments, _ = await _client(monkeypatch, Recorder()).sample_route_winds([KLAX, KJFK])
        samples = segments[0]["samples"]
        assert samples[0]["start_nm"] == 0
        assert samples[-1]["end_nm"] == pytest.approx(haversine_nm(*KLAX, *KJFK))
        for a, b in zip(samples, samples[1:]):
            assert a["end_nm"] == pytest.approx(b["start_nm"])


class TestSampleTimes:
    T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

    async def test_each_sample_uses_the_time_the_aircraft_gets_there(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds(_north(640), forecast_time=self.T0, cruise_speed_kt=120)
        part = haversine_nm(*_north(640)[0], *_north(640)[1]) / 4
        expected = [self.T0 + timedelta(hours=(part / 2 + k * part) / 120) for k in range(4)]
        for (_, _, when), want in zip(recorder.calls, expected):
            assert when == want

    async def test_later_legs_continue_from_the_distance_already_flown(self, monkeypatch):
        recorder = Recorder()
        waypoints = [(40.0, -100.0), (42.0, -100.0), (44.0, -100.0)]  # two legs of about 120 NM
        await _client(monkeypatch, recorder).sample_route_winds(waypoints, forecast_time=self.T0, cruise_speed_kt=120)
        first, second = recorder.calls[0][2], recorder.calls[1][2]
        assert abs((second - first) - timedelta(hours=1)) < timedelta(minutes=1)

    async def test_without_a_speed_every_sample_uses_the_departure_time(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds(_north(640), forecast_time=self.T0)
        assert {when for _, _, when in recorder.calls} == {self.T0}

    async def test_without_a_time_samples_have_no_time(self, monkeypatch):
        recorder = Recorder()
        await _client(monkeypatch, recorder).sample_route_winds(_north(640), cruise_speed_kt=120)
        assert {when for _, _, when in recorder.calls} == {None}


class TestLegSummary:
    async def test_crosswind_on_a_northbound_leg(self, monkeypatch):
        recorder = Recorder(lambda _i: _wind(20.0, 90.0))  # from the east
        segments, _ = await _client(monkeypatch, recorder).sample_route_winds(_north(300))
        (leg,) = segments
        assert leg["crosswind_component_kt"] == pytest.approx(20, abs=0.1)
        assert leg["headwind_component_kt"] == pytest.approx(0, abs=0.1)
        assert leg["wind_direction_deg"] == pytest.approx(90, abs=0.5) and leg["wind_speed_kt"] == pytest.approx(20, abs=0.1)

    async def test_head_and_tail_winds_average_out_but_stay_available_per_part(self, monkeypatch):
        recorder = Recorder([_wind(10.0, 0.0), _wind(10.0, 180.0)])  # headwind then tailwind on a northbound leg
        segments, _ = await _client(monkeypatch, recorder).sample_route_winds(_north(290))
        (leg,) = segments
        assert [round(s["headwind_component_kt"]) for s in leg["samples"]] == [10, -10]
        assert leg["headwind_component_kt"] == pytest.approx(0, abs=0.1)
        assert leg["tailwind_component_kt"] == 0

    async def test_opposite_winds_cancel_in_the_displayed_mean(self, monkeypatch):
        recorder = Recorder([_wind(20.0, 90.0), _wind(20.0, 270.0)])
        (leg,), _ = await _client(monkeypatch, recorder).sample_route_winds(_north(290))
        assert leg["wind_speed_kt"] == pytest.approx(0, abs=0.01)

    async def test_a_tailwind_leg_reports_a_negative_signed_headwind_and_a_tailwind(self, monkeypatch):
        recorder = Recorder(lambda _i: _wind(25.0, 180.0))
        (leg,), _ = await _client(monkeypatch, recorder).sample_route_winds(_north(300))
        assert leg["headwind_component_kt"] == pytest.approx(-25, abs=0.1)
        assert leg["tailwind_component_kt"] == pytest.approx(25, abs=0.1)

    async def test_missing_samples_take_the_average_of_the_others(self, monkeypatch, caplog):
        recorder = Recorder([_wind(10.0, 0.0), None, _wind(30.0, 0.0)])  # 3 parts on a 500 NM leg
        with caplog.at_level(logging.WARNING, logger="app.services.open_meteo"):
            (leg,), quality = await _client(monkeypatch, recorder).sample_route_winds(_north(500))
        assert [round(s["headwind_component_kt"]) for s in leg["samples"]] == [10, 20, 30]
        assert leg["wind_source"] == "pressure_level" and quality == "pressure_level"
        assert "Wind unavailable for 1 of 3 samples on leg 0" in caplog.text

    async def test_a_leg_without_any_wind_is_reported_as_unavailable(self, monkeypatch):
        recorder = Recorder(lambda _i: None)
        (leg,), quality = await _client(monkeypatch, recorder).sample_route_winds(_north(300))
        assert quality == "unavailable"
        assert leg["wind_source"] is None and leg["headwind_component_kt"] is None and "samples" not in leg

    async def test_any_surface_fallback_sample_marks_the_leg(self, monkeypatch):
        recorder = Recorder([_wind(), _wind(source="surface_fallback")])
        (leg,), quality = await _client(monkeypatch, recorder).sample_route_winds(_north(290))
        assert leg["wind_source"] == "surface_fallback" and quality == "surface_fallback"


KJFK_AIRPORT = make_airport("KJFK")
KORD_AIRPORT = make_airport("KORD", latitude=41.9786, longitude=-87.9048)


class TestCalculatorUsesTheSamples:
    @staticmethod
    def _install(monkeypatch, first_half_headwind: float, second_half_headwind: float):
        async def winds(waypoints, cruise_altitude_ft=10000, forecast_time=None, **_kwargs):
            (lat1, lon1), (lat2, lon2) = waypoints[0], waypoints[-1]
            length = haversine_nm(lat1, lon1, lat2, lon2)
            segments = []
            for i in range(len(waypoints) - 1):
                half = length / 2
                segments.append(
                    {
                        "segment_index": i,
                        "wind_speed_kt": 40.0,
                        "wind_direction_deg": 270.0,
                        "headwind_component_kt": 0.0,
                        "tailwind_component_kt": 0.0,
                        "crosswind_component_kt": 0.0,
                        "wind_altitude_ft": 8500,
                        "wind_pressure_level_hpa": 700,
                        "wind_source": "pressure_level",
                        "samples": [
                            {"start_nm": 0.0, "end_nm": half, "headwind_component_kt": first_half_headwind, "crosswind_component_kt": 0.0},
                            {"start_nm": half, "end_nm": length, "headwind_component_kt": second_half_headwind, "crosswind_component_kt": 0.0},
                        ],
                    }
                )
            return segments, "pressure_level"

        monkeypatch.setattr(open_meteo.open_meteo_client, "sample_route_winds", winds)
        from app.services import route_calculator as calculator_module

        monkeypatch.setattr(calculator_module.open_meteo_client, "sample_route_winds", winds)

    @staticmethod
    async def _direct(monkeypatch):
        aircraft = make_aircraft()  # cruise 122 kt, 12 min climb, 8 min descent
        result = await route_calculator.calculate(
            KJFK_AIRPORT,
            KORD_AIRPORT,
            aircraft,
            6.5,
            supabase=None,
            checkpoint_candidates=[],
            departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        return next(v for v in result["variants"] if v.name == "direct"), haversine_nm(
            KJFK_AIRPORT["latitude"], KJFK_AIRPORT["longitude"], KORD_AIRPORT["latitude"], KORD_AIRPORT["longitude"]
        )

    async def test_cruise_time_follows_the_wind_along_the_leg(self, monkeypatch):
        self._install(monkeypatch, first_half_headwind=40, second_half_headwind=-40)
        direct, length = await self._direct(monkeypatch)
        climb_nm = 12 / 60 * 122 * CLIMB_SPEED_FACTOR
        descent_nm = 8 / 60 * 122 * DESCENT_SPEED_FACTOR
        half = length / 2
        first = half - climb_nm  # cruise distance in the first half (the climb is flown at the start)
        second = half - descent_nm
        expected = 20 + first / (122 - 40) * 60 + second / (122 + 40) * 60
        assert direct.ete_minutes == pytest.approx(expected, abs=0.05)

    async def test_a_headwind_on_one_half_costs_more_than_the_tailwind_on_the_other_saves(self, monkeypatch):
        self._install(monkeypatch, first_half_headwind=40, second_half_headwind=-40)
        windy, length = await self._direct(monkeypatch)
        self._install(monkeypatch, first_half_headwind=0, second_half_headwind=0)
        calm, _ = await self._direct(monkeypatch)
        assert windy.ete_minutes > calm.ete_minutes  # head/tail winds of equal size do not cancel in time

    async def test_the_stored_leg_values_are_the_leg_mean(self, monkeypatch):
        self._install(monkeypatch, first_half_headwind=40, second_half_headwind=-40)
        direct, _ = await self._direct(monkeypatch)
        (segment,) = direct.segments
        assert "samples" not in segment and "crosswind_component_kt" not in segment  # transient: not stored
        assert segment["wind_speed_kt"] == 40.0


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestGridSnapping:
    @pytest.fixture
    def http(self, monkeypatch):
        requests: list[dict] = []
        store: dict[str, dict] = {}
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def get(self, _url, params=None):
                requests.append(params)
                hours = int(params["forecast_days"]) * 24
                level = next(key for key in params["hourly"].split(",") if "hPa" in key and key.startswith("windspeed"))
                suffix = level.removeprefix("windspeed_")
                return _Response(
                    {
                        "hourly": {
                            "time": [(today + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)],
                            level: [12.0] * hours,
                            f"winddirection_{suffix}": [270.0] * hours,
                            "windspeed_10m": [5.0] * hours,
                            "winddirection_10m": [270.0] * hours,
                        }
                    }
                )

        class MemoryCache:
            def get(self, key):
                return store.get(key)

            def set(self, key, value, _ttl=None):
                store[key] = value

        monkeypatch.setattr(open_meteo.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(open_meteo, "cache_service", MemoryCache())
        monkeypatch.setattr(settings, "cache_wind_ttl", 3600)
        return requests, store

    async def test_requests_use_the_forecast_grid(self, http):
        requests, _ = http
        await OpenMeteoClient().get_wind_at_point(40.1, -100.12, 8500, datetime.now(timezone.utc))
        assert (requests[0]["latitude"], requests[0]["longitude"]) == (40.0, -100.0)

    async def test_nearby_points_share_one_request(self, http):
        requests, store = http
        when = datetime.now(timezone.utc)
        first = await OpenMeteoClient().get_wind_at_point(40.05, -100.04, 8500, when)
        second = await OpenMeteoClient().get_wind_at_point(39.96, -99.93, 8500, when)
        assert len(requests) == 1
        assert first == second
        assert len(store) == 1

    async def test_points_in_different_cells_are_requested_separately(self, http):
        requests, _ = http
        when = datetime.now(timezone.utc)
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, when)
        await OpenMeteoClient().get_wind_at_point(40.5, -100.0, 8500, when)
        assert len(requests) == 2

    async def test_the_same_cell_at_another_hour_is_requested_again(self, http):
        requests, _ = http
        when = datetime.now(timezone.utc).replace(minute=0)
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, when)
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, when + timedelta(hours=3))
        assert len(requests) == 2
