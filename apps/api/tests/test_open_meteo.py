"""Open-Meteo wind lookup: the forecast hour must match the departure time across the whole allowed window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.planning_constraints import FORECAST_HORIZON_DAYS
from app.services import open_meteo
from app.services.open_meteo import OPEN_METEO_FORECAST_DAYS, OpenMeteoClient


def _hours(start: datetime, count: int) -> list[str]:
    return [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(count)]


class TestHourIndex:
    START = datetime(2026, 11, 14, tzinfo=timezone.utc)
    TIMES = _hours(START, 48)

    def test_exact_hour(self):
        assert OpenMeteoClient._hour_index(self.TIMES, self.START + timedelta(hours=10)) == 10

    def test_minutes_are_rounded_down_to_the_hour(self):
        assert OpenMeteoClient._hour_index(self.TIMES, self.START + timedelta(hours=10, minutes=40)) == 10

    def test_non_utc_offsets_are_converted(self):
        local = (self.START + timedelta(hours=10)).astimezone(timezone(timedelta(hours=-8)))
        assert OpenMeteoClient._hour_index(self.TIMES, local) == 10

    def test_time_before_the_forecast_starts_uses_the_first_hour(self):
        assert OpenMeteoClient._hour_index(self.TIMES, self.START - timedelta(hours=1)) == 0

    def test_last_hour_is_reachable(self):
        assert OpenMeteoClient._hour_index(self.TIMES, self.START + timedelta(hours=47, minutes=30)) == 47

    def test_time_after_the_forecast_is_not_mapped_to_hour_zero(self):
        # Used to return 0 (min(len - 1, 0)), i.e. wind from the start of today.
        assert OpenMeteoClient._hour_index(self.TIMES, self.START + timedelta(hours=48)) is None

    def test_empty_forecast(self):
        assert OpenMeteoClient._hour_index([], self.START) is None

    def test_unparsable_entries_are_skipped(self):
        times = ["garbage", *self.TIMES]
        assert OpenMeteoClient._hour_index(times, self.START + timedelta(hours=2)) == 3

    def test_omitted_time_means_now(self):
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        assert OpenMeteoClient._hour_index(_hours(start, 48), None) == now.hour


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _install_fake_open_meteo(monkeypatch, today: datetime):
    """Fake the HTTP layer: the wind speed at hour i is i knots, so the speed reveals which hour was used."""
    requests: list[dict] = []

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
            hourly = {
                "time": _hours(today, hours),
                "windspeed_10m": [5.0] * hours,
                "winddirection_10m": [270.0] * hours,
            }
            for key in params["hourly"].split(","):
                if key.startswith("windspeed_") and "hPa" in key:  # every requested level carries the hour index
                    hourly[key] = [float(i) for i in range(hours)]
                    hourly[key.replace("windspeed_", "winddirection_")] = [270.0] * hours
            return _Response({"hourly": hourly})

    class NoCache:
        def get(self, _key):
            return None

        def set(self, *_args):
            return None

    monkeypatch.setattr(open_meteo.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(open_meteo, "cache_service", NoCache())
    return requests


@pytest.fixture
def today():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


class TestWindAtPoint:
    async def test_request_covers_the_whole_departure_window(self, monkeypatch, today):
        requests = _install_fake_open_meteo(monkeypatch, today)
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, today + timedelta(hours=5))
        assert requests[0]["forecast_days"] == OPEN_METEO_FORECAST_DAYS == FORECAST_HORIZON_DAYS + 1

    async def test_departure_on_the_last_allowed_day_uses_the_matching_hour(self, monkeypatch, today):
        _install_fake_open_meteo(monkeypatch, today)
        departure = datetime.now(timezone.utc) + timedelta(days=FORECAST_HORIZON_DAYS) - timedelta(minutes=1)
        wind = await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, departure)
        expected_hour = int((departure.replace(minute=0, second=0, microsecond=0) - today).total_seconds() // 3600)
        assert expected_hour >= FORECAST_HORIZON_DAYS * 24, "scenario must fall in the last allowed day"
        assert wind is not None
        assert wind["wind_speed_kt"] == expected_hour  # used to be hour 0 (speed 0.0)
        assert wind["wind_source"] == "pressure_level"

    async def test_time_beyond_the_returned_forecast_is_unavailable(self, monkeypatch, today):
        _install_fake_open_meteo(monkeypatch, today)
        beyond = today + timedelta(days=OPEN_METEO_FORECAST_DAYS, hours=2)
        assert await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, beyond) is None

    async def test_sample_route_winds_reports_unavailable_beyond_the_forecast(self, monkeypatch, today):
        _install_fake_open_meteo(monkeypatch, today)
        beyond = today + timedelta(days=OPEN_METEO_FORECAST_DAYS, hours=2)
        segments, quality = await OpenMeteoClient().sample_route_winds(
            [(40.0, -100.0), (41.0, -95.0)], cruise_altitude_ft=8500, forecast_time=beyond
        )
        assert quality == "unavailable"
        assert segments[0]["wind_speed_kt"] is None

    async def test_cache_key_uses_the_utc_hour(self, monkeypatch, today):
        _install_fake_open_meteo(monkeypatch, today)
        keys: list[str] = []

        class RecordingCache:
            def get(self, key):
                keys.append(key)
                return None

            def set(self, *_args):
                return None

        monkeypatch.setattr(open_meteo, "cache_service", RecordingCache())
        local = (today + timedelta(hours=10)).astimezone(timezone(timedelta(hours=5)))  # 15:00+05:00 == 10:00Z
        await OpenMeteoClient().get_wind_at_point(40.0, -100.0, 8500, local)
        assert keys[0].endswith(f"{(today + timedelta(hours=10)):%Y-%m-%dT%H}")
