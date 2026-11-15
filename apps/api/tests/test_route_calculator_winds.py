"""Missing or degraded winds must be reported: legs without wind data are planned with zero wind."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import route_calculator as calculator_module
from app.services.open_meteo import wind_quality_from_segments
from app.services.route_calculator import route_calculator, wind_quality_warnings
from tests.fakes import make_aircraft, make_airport


def _legs(*sources):
    return [{"segment_index": i, "wind_source": source} for i, source in enumerate(sources)]


class TestWindQualityFromSegments:
    @pytest.mark.parametrize(
        ("sources", "expected"),
        [
            ([], "unavailable"),
            ([None], "unavailable"),
            ([None, None], "unavailable"),
            (["pressure_level"], "pressure_level"),
            (["pressure_level", "pressure_level"], "pressure_level"),
            (["surface_fallback", "surface_fallback"], "surface_fallback"),
            (["pressure_level", "surface_fallback"], "mixed"),
            (["pressure_level", None], "partial"),
            ([None, "surface_fallback"], "partial"),
        ],
    )
    def test_classification(self, sources, expected):
        assert wind_quality_from_segments(_legs(*sources)) == expected


class TestWindQualityWarnings:
    def test_no_wind_at_all_is_called_out(self):
        (warning,) = wind_quality_warnings(_legs(None, None))
        assert "unavailable" in warning and "zero wind" in warning

    def test_empty_route_counts_as_no_wind(self):
        assert any("zero wind" in w for w in wind_quality_warnings([]))

    def test_good_winds_produce_no_warning(self):
        assert wind_quality_warnings(_legs("pressure_level", "pressure_level")) == []

    def test_surface_fallback_everywhere(self):
        (warning,) = wind_quality_warnings(_legs("surface_fallback", "surface_fallback"))
        assert "surface wind fallback" in warning

    def test_some_legs_on_surface_wind(self):
        (warning,) = wind_quality_warnings(_legs("pressure_level", "surface_fallback"))
        assert "1 of 2 legs" in warning and "surface wind" in warning

    def test_some_legs_without_wind(self):
        (warning,) = wind_quality_warnings(_legs("pressure_level", None, "pressure_level"))
        assert "1 of 3 legs" in warning and "zero wind" in warning

    def test_missing_and_fallback_legs_are_both_reported(self):
        warnings = wind_quality_warnings(_legs(None, "surface_fallback"))
        assert len(warnings) == 2
        assert any("1 of 2 legs" in w and "zero wind" in w for w in warnings)
        assert any("surface wind fallback" in w for w in warnings)


def _fake_winds(source: str | None):
    async def sample(waypoints, cruise_altitude_ft=10000, forecast_time=None):
        segments = []
        for i in range(len(waypoints) - 1):
            has_wind = source is not None
            segments.append(
                {
                    "segment_index": i,
                    "wind_speed_kt": 0.0 if has_wind else None,
                    "wind_direction_deg": 270.0 if has_wind else None,
                    "headwind_component_kt": 0.0 if has_wind else None,
                    "tailwind_component_kt": 0.0 if has_wind else None,
                    "wind_altitude_ft": 8500 if has_wind else None,
                    "wind_pressure_level_hpa": 700 if source == "pressure_level" else None,
                    "wind_source": source,
                }
            )
        return segments, wind_quality_from_segments(segments)

    return sample


async def _calculate(monkeypatch, source: str | None):
    monkeypatch.setattr(calculator_module.open_meteo_client, "sample_route_winds", _fake_winds(source))
    departure = make_airport("KJFK")
    destination = make_airport("KLAX", latitude=33.9425, longitude=-118.4081)
    return await route_calculator.calculate(
        departure,
        destination,
        make_aircraft(),
        6.5,
        supabase=None,
        checkpoint_candidates=[],
        departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
    )


class TestCalculateReportsWindQuality:
    async def test_no_wind_data_is_flagged_and_stored(self, monkeypatch):
        result = await _calculate(monkeypatch, None)
        assert result["wind_data_quality"] == "unavailable"
        assert any("zero wind" in w for w in result["warnings"])
        assert all(s["wind_speed_kt"] is None for s in result["primary"].segments)

    async def test_surface_fallback_is_flagged(self, monkeypatch):
        result = await _calculate(monkeypatch, "surface_fallback")
        assert result["wind_data_quality"] == "surface_fallback"
        assert any("surface wind fallback" in w for w in result["warnings"])

    async def test_pressure_level_winds_need_no_wind_warning(self, monkeypatch):
        result = await _calculate(monkeypatch, "pressure_level")
        assert result["wind_data_quality"] == "pressure_level"
        assert not any("wind" in w.lower() and ("zero wind" in w or "fallback" in w) for w in result["warnings"])

    async def test_quality_describes_the_returned_route(self, monkeypatch):
        result = await _calculate(monkeypatch, "pressure_level")
        assert result["wind_data_quality"] == wind_quality_from_segments(result["primary"].segments)
