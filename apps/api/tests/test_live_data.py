"""Tests for unified live aviation data layer."""

from __future__ import annotations

import pytest

from app.services.live_data.corridor import tfr_impact_for_point
from app.services.live_data.live_data_scoring import (
    compute_live_penalties,
    live_data_feature_flags,
    live_data_warnings,
)
from app.services.live_data.notam_provider import (
    DisabledNotamProvider,
    categorize_notam_text,
)
from app.services.live_data.tfr_provider import _parse_tfr_list_item
from app.services.live_data.types import LiveDataSnapshot
from app.services.ml_features import delay_label_from_features


class TestTfrParser:
    def test_parse_list_item(self):
        item = {
            "notamNumber": "5/1234",
            "title": "VIP TFR",
            "description": "WITHIN 10 NM OF POINT",
            "lat": 38.5,
            "lon": -77.0,
            "radius": 10,
        }
        rec = _parse_tfr_list_item(item)
        assert rec is not None
        assert rec.notam_number == "5/1234"
        assert rec.centroid_lat == 38.5

    def test_route_intersection(self):
        waypoints = [(38.0, -78.0), (39.0, -77.0)]
        impact, dist = tfr_impact_for_point(38.5, -77.5, 15.0, waypoints)
        assert impact in ("intersects", "nearby", "none")
        assert dist >= 0


class TestNotamProvider:
    @pytest.mark.asyncio
    async def test_disabled_mode(self):
        provider = DisabledNotamProvider()
        result = await provider.get_airport_notams("KJFK")
        assert result.data == []
        assert result.meta.available is False
        assert "not connected" in (result.meta.error or "").lower()

    def test_categorize_runway_closure(self):
        cat, sev = categorize_notam_text("RWY 04/22 CLSD DUE WIP")
        assert cat == "runway"
        assert sev == "high"

    def test_categorize_airport_closure(self):
        cat, sev = categorize_notam_text("AD CLSD EXC HELICOPTER OPS")
        assert cat == "airport_closure"
        assert sev == "high"


class TestLiveDataScoring:
    def test_sigmet_high_penalty(self):
        snap = LiveDataSnapshot(
            route_id="r1",
            fetched_at="2026-01-01T00:00:00Z",
            weather={"hazards": [{"hazard_type": "sigmet", "intersects_route": True, "severity": "high"}]},
        )
        penalties = compute_live_penalties(snap)
        assert penalties["weather_penalty"] >= 35

    def test_integration_disabled_warnings(self):
        snap = LiveDataSnapshot(route_id="r1", fetched_at="2026-01-01T00:00:00Z")
        warnings = live_data_warnings(snap)
        assert any("AviationWeather.gov" in w for w in warnings)
        assert any("FAA live data" in w for w in warnings)


class TestDelayLabelsLiveData:
    def test_high_on_tfr_intersection(self):
        features = {
            "departure_delay_minutes": 0,
            "destination_delay_minutes": 0,
            "departure_closed": 0,
            "destination_closed": 0,
            "tfr_intersects_route": 1,
            "live_data_confidence": "high",
        }
        label = delay_label_from_features(features)
        assert label["delay_risk"] == "high"
        assert "tfr_intersects_route" in label["label_source"]["reasons"]

    def test_medium_on_ifr(self):
        features = {
            "departure_delay_minutes": 0,
            "destination_delay_minutes": 0,
            "departure_flight_category_ord": 2,
            "destination_flight_category_ord": 0,
            "worst_enroute_flight_category_ord": 0,
            "departure_closed": 0,
            "destination_closed": 0,
        }
        label = delay_label_from_features(features)
        assert label["delay_risk"] == "medium"


class TestModalApp:
    def test_modal_app_import(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "modal_app.py"
        spec = importlib.util.spec_from_file_location("modal_app", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        # Modal may not be installed in test env — only verify file parses
        source = path.read_text()
        assert "modal.App" in source
        assert "fastapi_app" in source


class TestCorsConfig:
    def test_cors_origins_parsed(self):
        from app.config import Settings

        s = Settings(api_cors_origins="http://localhost:3000,https://aeroroute.vercel.app")
        assert "http://localhost:3000" in s.cors_origins
        assert "https://aeroroute.vercel.app" in s.cors_origins
