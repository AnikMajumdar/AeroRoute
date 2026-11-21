"""Provenance: copilot context and tool results must not claim data sources or refreshes that did not happen."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import copilot_tools
from app.services.aviation_weather import INTEGRATION_DISABLED_MESSAGE as AWC_MSG
from app.services.faa_nas import INTEGRATION_DISABLED_MESSAGE as FAA_MSG
from app.services import route_calculator as calculator_module
from app.services.live_data.live_data_scoring import live_data_warnings
from app.services.open_meteo import wind_quality_from_segments
from app.services.route_calculator import route_calculator
from app.services.route_context_bundle import get_route_context, provider_status, weather_source_label
from tests.fakes import FakeSupabase, make_aircraft, make_airport, seed_route

TFR_DISABLED = {"source_name": "FAA TFR (disabled)", "available": False, "error": FAA_MSG}
HAZARDS_DISABLED = {"source_name": "AviationWeather.gov (disabled)", "available": False, "error": AWC_MSG}
NOTAM_DISABLED = {"source_name": "NOTAM (disabled)", "available": False, "error": "NOTAM integration not connected."}


def _route(user_id: str = "user_A") -> tuple[FakeSupabase, str]:
    db = FakeSupabase()
    return db, seed_route(db, user_id=user_id)["result_id"]


def _store_snapshot(db: FakeSupabase, route_id: str, sources: dict) -> None:
    snapshot = {
        "fetched_at": "2026-11-14T00:00:00+00:00",
        "sources": sources,
        "restrictions": {"tfrs": [], "notams": [], "notam_connected": False},
        "weather": {"hazards": []},
        "confidence": {"level": "low"},
        "warnings": [],
    }
    db.tables.setdefault("live_data_snapshots", []).append(
        {"route_result_id": route_id, "snapshot": snapshot, "fetched_at": snapshot["fetched_at"]}
    )


class TestWeatherRefreshIsNotFaked:
    async def test_requested_refresh_does_not_stamp_a_time(self):
        db, route_id = _route()
        ctx = await get_route_context(db, route_id, "user_A", refresh_weather=True)
        assert ctx["data_source_timestamps"]["weather_refreshed_at"] is None  # used to be "now"
        assert ctx["weather_refresh"]["requested"] is True
        assert ctx["weather_refresh"]["performed"] is False
        assert "not connected" in ctx["weather_refresh"]["reason"]

    async def test_no_refresh_requested(self):
        db, route_id = _route()
        ctx = await get_route_context(db, route_id, "user_A")
        assert ctx["data_source_timestamps"]["weather_refreshed_at"] is None
        assert ctx["weather_refresh"] == {"requested": False, "performed": False}


class TestWeatherSourceLabels:
    async def test_missing_weather_is_not_attributed_to_aviationweather(self):
        db, route_id = _route()
        ctx = await get_route_context(db, route_id, "user_A")
        for side in ("departure_weather", "destination_weather"):
            assert ctx[side]["metar"] == {"available": False}
            assert ctx[side]["source"] == weather_source_label(False)
            assert "not connected" in ctx[side]["source"]

    async def test_stored_metar_is_labelled_as_calculation_time_data(self):
        db, route_id = _route()
        db.rows("route_results")[0]["departure_weather"] = {
            "metar": {"flight_category": "VFR", "raw": "KJFK 140051Z 28008KT 10SM CLR 12/03 A3012"},
            "faa_status": {},
        }
        ctx = await get_route_context(db, route_id, "user_A")
        assert ctx["departure_weather"]["metar"]["available"] is True
        assert ctx["departure_weather"]["source"] == weather_source_label(True)
        assert "calculation time" in ctx["departure_weather"]["source"]
        assert ctx["destination_weather"]["source"] == weather_source_label(False)


class TestWeatherTools:
    async def test_refresh_route_weather_reports_that_nothing_was_refreshed(self):
        db, route_id = _route()
        result = await copilot_tools.refresh_route_weather(db, route_id, "user_A")
        assert result["refresh_performed"] is False
        assert "live refresh" not in result["source"].lower()
        assert result["source"] == weather_source_label(False)
        assert result["timestamp"]["weather_refreshed_at"] is None
        assert "No live weather refresh was performed" in result["note"]

    async def test_weather_risk_summary_has_an_honest_source(self):
        db, route_id = _route()
        result = await copilot_tools.get_weather_risk_summary(db, route_id, "user_A")
        assert result["source"] == weather_source_label(False)
        assert result["weather_refresh"]["performed"] is False
        assert "departure METAR" in result["missing_data"]

    async def test_weather_risk_summary_with_stored_checkpoint_weather(self):
        db, route_id = _route()
        db.rows("route_results")[0]["weather_checkpoints"] = [
            {"icao": "KORD", "name": "Chicago", "flight_category": "IFR", "metar": {"flight_category": "IFR", "raw": "KORD ..."}}
        ]
        result = await copilot_tools.get_weather_risk_summary(db, route_id, "user_A")
        assert result["source"] == weather_source_label(True)


class TestProviderStatus:
    def test_disabled_provider(self):
        status = provider_status({"sources": {"tfr": TFR_DISABLED}}, "tfr", "FAA TFR")
        assert status == {"source": "FAA TFR (disabled)", "connected": False, "message": FAA_MSG}

    def test_connected_provider(self):
        meta = {"source_name": "FAA TFR (tfr.faa.gov)", "available": True, "error": None}
        status = provider_status({"sources": {"tfr": meta}}, "tfr", "FAA TFR")
        assert status == {"source": "FAA TFR (tfr.faa.gov)", "connected": True, "message": None}

    def test_available_but_errored_provider_is_not_connected(self):
        meta = {"source_name": "FAA NMS NOTAM", "available": True, "error": "HTTP 503"}
        assert provider_status({"sources": {"notam": meta}}, "notam", "NOTAM")["connected"] is False

    def test_no_snapshot(self):
        status = provider_status(None, "tfr", "FAA TFR")
        assert status["source"] == "FAA TFR (no snapshot stored)"
        assert status["connected"] is False and status["message"]


class TestLiveDataTools:
    async def test_tfr_summary_uses_the_recorded_provider_state(self):
        db, route_id = _route()
        _store_snapshot(db, route_id, {"tfr": TFR_DISABLED})
        result = await copilot_tools.get_tfr_summary(db, route_id, "user_A")
        assert result["source"] == "FAA TFR (disabled)"  # used to claim "FAA TFR (tfr.faa.gov)"
        assert result["connected"] is False
        assert "not connected" in result["message"]

    async def test_tfr_summary_follows_a_connected_provider(self):
        db, route_id = _route()
        _store_snapshot(db, route_id, {"tfr": {"source_name": "FAA TFR (tfr.faa.gov)", "available": True, "error": None}})
        result = await copilot_tools.get_tfr_summary(db, route_id, "user_A")
        assert result["source"] == "FAA TFR (tfr.faa.gov)"
        assert result["connected"] is True and result["message"] is None

    async def test_tfr_summary_without_a_snapshot(self):
        db, route_id = _route()
        result = await copilot_tools.get_tfr_summary(db, route_id, "user_A")
        assert result["source"] == "FAA TFR (no snapshot stored)"
        assert result["connected"] is False

    async def test_hazard_summary_uses_the_recorded_provider_state(self):
        db, route_id = _route()
        _store_snapshot(db, route_id, {"weather_hazards": HAZARDS_DISABLED})
        result = await copilot_tools.get_weather_hazard_summary(db, route_id, "user_A")
        assert result["source"] == "AviationWeather.gov (disabled)"  # used to claim "AviationWeather.gov"
        assert result["connected"] is False
        assert result["hazards"] == []

    async def test_notam_summary_uses_the_recorded_provider_name(self):
        db, route_id = _route()
        _store_snapshot(db, route_id, {"notam": NOTAM_DISABLED})
        result = await copilot_tools.get_notam_summary(db, route_id, "user_A")
        assert result["source"] == "NOTAM (disabled)"
        assert result["notam_connected"] is False


class TestWarningsAreNotRepeated:
    def test_live_data_warnings_are_unique_and_ordered(self):
        snapshot = {"warnings": [FAA_MSG, AWC_MSG, "NOTAM integration not connected.", FAA_MSG]}
        warnings = live_data_warnings(snapshot)
        assert warnings == [AWC_MSG, FAA_MSG, "NOTAM integration not connected."]

    async def test_calculated_route_has_no_duplicate_warnings(self, monkeypatch):
        async def pressure_winds(waypoints, cruise_altitude_ft=10000, forecast_time=None, **_kwargs):
            segments = [
                {"segment_index": i, "wind_speed_kt": 0.0, "wind_direction_deg": 270.0, "headwind_component_kt": 0.0,
                 "tailwind_component_kt": 0.0, "wind_altitude_ft": 8500, "wind_pressure_level_hpa": 700,
                 "wind_source": "pressure_level"}
                for i in range(len(waypoints) - 1)
            ]
            return segments, wind_quality_from_segments(segments)

        monkeypatch.setattr(calculator_module.open_meteo_client, "sample_route_winds", pressure_winds)
        result = await route_calculator.calculate(
            make_airport("KJFK"),
            make_airport("KLAX", latitude=33.9425, longitude=-118.4081),
            make_aircraft(),
            6.5,
            supabase=None,
            checkpoint_candidates=[],
            departure_time=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        assert result["warnings"], "the disabled integrations must still be mentioned"
        assert len(result["warnings"]) == len(set(result["warnings"]))
