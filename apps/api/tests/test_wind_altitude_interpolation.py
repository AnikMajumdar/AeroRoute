"""Winds at the cruise altitude are interpolated between the two pressure levels around it, not taken from the nearest."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services import open_meteo
from app.services.open_meteo import OpenMeteoClient
from app.services.wind_altitude import (
    PRESSURE_LEVELS_HPA,
    cruise_altitude_to_pressure_level_hpa,
    interpolate_wind,
    pressure_levels_around,
    uv_to_wind,
    wind_to_uv,
)


class TestPressureLevelsAround:
    def test_between_two_levels(self):
        lower, upper, weight = pressure_levels_around(8500)
        assert (lower, upper) == ((850, 5000), (700, 10000))
        assert weight == pytest.approx(0.7)

    @pytest.mark.parametrize(("altitude", "level"), [(5000, 850), (10000, 700), (0, 1000), (39000, 200)])
    def test_exactly_on_a_level_uses_only_that_level(self, altitude, level):
        lower, upper, weight = pressure_levels_around(altitude)
        assert lower == upper and lower[0] == level and weight == 0.0

    @pytest.mark.parametrize(("altitude", "level"), [(-1500, 1000), (45000, 200)])
    def test_outside_the_range_clamps_to_the_end_level(self, altitude, level):
        lower, upper, weight = pressure_levels_around(altitude)
        assert lower == upper and lower[0] == level and weight == 0.0

    @pytest.mark.parametrize("altitude", range(500, 39000, 500))
    def test_the_levels_enclose_the_altitude(self, altitude):
        lower, upper, weight = pressure_levels_around(altitude)
        assert lower[1] <= altitude <= upper[1]
        assert 0.0 <= weight < 1.0
        if lower != upper:
            assert lower[1] + weight * (upper[1] - lower[1]) == pytest.approx(altitude)

    def test_nearest_level_alone_would_be_1500_ft_off(self):
        level, altitude = cruise_altitude_to_pressure_level_hpa(8500)
        assert (level, altitude) == (700, 10000)  # the old behaviour: 8,500 ft was flown on the 10,000 ft wind

    def test_level_table_is_ordered_by_altitude(self):
        altitudes = [alt for _, alt in PRESSURE_LEVELS_HPA]
        assert altitudes == sorted(altitudes)


class TestWindVectors:
    @pytest.mark.parametrize(("speed", "direction"), [(20, 0), (20, 90), (15, 225), (30, 359)])
    def test_round_trip(self, speed, direction):
        assert uv_to_wind(*wind_to_uv(speed, direction)) == pytest.approx((speed, direction))

    def test_wind_from_the_west_blows_east(self):
        u, v = wind_to_uv(10, 270)
        assert (round(u, 6), round(v, 6)) == (10.0, 0.0)

    def test_calm_keeps_the_given_direction(self):
        assert uv_to_wind(0.0, 0.0, 123.0) == (0.0, 123.0)


class TestInterpolateWind:
    def test_same_direction_interpolates_the_speed(self):
        speed, direction = interpolate_wind((10, 270), (30, 270), 0.7)
        assert speed == pytest.approx(24)
        assert direction == pytest.approx(270)

    def test_weights_zero_and_one_return_the_levels(self):
        assert interpolate_wind((10, 270), (30, 300), 0) == pytest.approx((10, 270))
        assert interpolate_wind((10, 270), (30, 300), 1) == pytest.approx((30, 300))

    def test_opposite_winds_cancel_halfway(self):
        speed, _ = interpolate_wind((20, 270), (20, 90), 0.5)
        assert speed == pytest.approx(0, abs=1e-9)

    def test_a_veering_wind_is_interpolated_on_its_components(self):
        # 10 kt from the west and 10 kt from the north: halfway the vector is 7.07 kt from the north-west
        speed, direction = interpolate_wind((10, 270), (10, 360), 0.5)
        assert speed == pytest.approx(10 / math.sqrt(2))
        assert direction == pytest.approx(315)

    def test_a_calm_pair_keeps_the_lower_direction(self):
        assert interpolate_wind((0, 40), (0, 200), 0.5) == (0.0, 40)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Fake Open-Meteo and cache. The returned dict holds the editable per-level winds and what the code did.

    ``levels`` maps hPa -> (speed_kt, direction_deg), ``surface`` is the 10 m wind (None = no data),
    ``requests`` the query parameters of every HTTP call and ``store`` the cache contents.
    """
    state = {
        "levels": {925: (5.0, 270.0), 850: (10.0, 270.0), 700: (30.0, 270.0), 600: (40.0, 270.0)},
        "surface": (5.0, 270.0),
        "requests": [],
        "store": {},
    }
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def series(hours: int, value: float | None) -> list[float | None]:
        return [value] * hours

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, _url, params=None):
            state["requests"].append(params)
            hours = int(params["forecast_days"]) * 24
            hourly: dict[str, list] = {"time": [(today + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]}
            for key in params["hourly"].split(","):
                if key.startswith("windspeed_") and "hPa" in key:
                    speed, direction = state["levels"].get(int(key.removeprefix("windspeed_").removesuffix("hPa")), (None, None))
                    hourly[key] = series(hours, speed)
                    hourly[key.replace("windspeed_", "winddirection_")] = series(hours, direction)
            surface_speed, surface_direction = state["surface"] or (None, None)
            hourly["windspeed_10m"] = series(hours, surface_speed)
            hourly["winddirection_10m"] = series(hours, surface_direction)
            return _Response({"hourly": hourly})

    class MemoryCache:
        def get(self, key):
            return state["store"].get(key)

        def set(self, key, value, ttl_seconds):
            state["store"][key] = value

    monkeypatch.setattr(open_meteo.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(open_meteo, "cache_service", MemoryCache())
    state["when"] = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return state


class TestGetWindAtPoint:
    async def test_the_wind_is_interpolated_between_the_levels(self, http):
        wind = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        assert wind["wind_speed_kt"] == pytest.approx(24.0)  # 850 hPa: 10 kt, 700 hPa: 30 kt, 70% of the way up
        assert wind["wind_direction_deg"] == pytest.approx(270.0)
        assert wind["wind_source"] == "pressure_level"

    async def test_both_levels_come_from_a_single_request(self, http):
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        (request,) = http["requests"]
        variables = request["hourly"].split(",")
        assert {"windspeed_850hPa", "winddirection_850hPa", "windspeed_700hPa", "winddirection_700hPa"} <= set(variables)
        assert "windspeed_10m" in variables

    async def test_the_result_reports_the_cruise_altitude_and_the_nearest_level(self, http):
        near_upper = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        assert near_upper["wind_altitude_ft"] == 8500  # used to be the level's 10,000 ft
        assert near_upper["wind_pressure_level_hpa"] == 700
        near_lower = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 6000, http["when"])
        assert near_lower["wind_altitude_ft"] == 6000
        assert near_lower["wind_pressure_level_hpa"] == 850

    async def test_an_altitude_on_a_level_requests_only_that_level(self, http):
        wind = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 10000, http["when"])
        assert wind["wind_speed_kt"] == pytest.approx(30.0)
        variables = http["requests"][0]["hourly"]
        assert "windspeed_700hPa" in variables and "850hPa" not in variables and "600hPa" not in variables

    async def test_a_level_without_data_falls_back_to_the_surface_wind(self, http):
        del http["levels"][850]
        wind = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        assert wind["wind_source"] == "surface_fallback"
        assert wind["wind_speed_kt"] == 5.0
        assert wind["wind_pressure_level_hpa"] is None and wind["wind_altitude_ft"] == 10

    async def test_no_data_at_all_is_unavailable_and_not_cached(self, http):
        http["levels"].clear()
        http["surface"] = None
        wind = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        assert wind is None
        assert http["store"] == {}

    async def test_the_cache_holds_the_raw_winds_so_other_altitudes_reuse_it(self, http):
        client = OpenMeteoClient()
        first = await client.get_wind_at_point(40.0, -100.0, 8500, http["when"])
        second = await client.get_wind_at_point(40.0, -100.0, 7000, http["when"])  # same 850/700 pair
        assert len(http["requests"]) == 1
        assert second["wind_speed_kt"] == pytest.approx(10 + 0.4 * 20)
        assert second["wind_speed_kt"] != first["wind_speed_kt"]

    async def test_another_level_pair_is_requested_separately(self, http):
        client = OpenMeteoClient()
        await client.get_wind_at_point(40.0, -100.0, 8500, http["when"])
        await client.get_wind_at_point(40.0, -100.0, 12000, http["when"])  # 700/600 pair
        assert len(http["requests"]) == 2

    async def test_the_cached_value_is_plain_json(self, http):
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        (cached,) = http["store"].values()
        assert json.loads(json.dumps(cached)) == cached
        assert set(cached["levels"]) == {"850", "700"}

    async def test_the_improvement_over_the_nearest_level(self, http):
        wind = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, http["when"])
        nearest_level_speed = http["levels"][700][0]  # what the old code reported for 8,500 ft
        assert nearest_level_speed == 30.0
        assert wind["wind_speed_kt"] < nearest_level_speed
