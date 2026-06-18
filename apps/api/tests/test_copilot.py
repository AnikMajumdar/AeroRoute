import pytest
from unittest.mock import AsyncMock, patch

from app.services.copilot import (
    SUGGESTED_QUESTIONS,
    answer_with_llm,
    build_route_context,
    is_copilot_available,
)
from app.services.faa_nas_parser import parse_faa_airport_status


@pytest.fixture
def sample_route_data():
    route = {
        "id": "route-1",
        "primary_distance_nm": 2145.0,
        "primary_ete_minutes": 702.0,
        "primary_fuel_burn_gal": 198.5,
        "primary_fuel_cost_usd": 1290.0,
        "primary_score": 82.0,
        "alternate_distance_nm": 2180.0,
        "alternate_ete_minutes": 715.0,
        "alternate_fuel_burn_gal": 205.0,
        "alternate_score": 78.0,
        "wind_data_quality": "pressure_level",
        "warnings": ["Educational estimate only"],
        "fuel_breakdown": {
            "trip_fuel_gal": 198.5,
            "reserve_fuel_gal": 25.8,
            "total_required_gal": 224.3,
        },
        "normalized_score_breakdown": {
            "composite_score": 82,
            "component_scores": {"time": 85, "fuel": 80, "weather": 90, "delay": 75, "diversion": 80},
        },
        "weather_checkpoints": [{"icao": "KORD", "flight_category": "VFR"}],
        "route_candidates": [{"name": "direct", "score": 82, "selected": True}],
    }
    request = {"route_preference": "balanced", "departure_time": "2026-06-16T12:00:00Z"}
    segments = [
        {
            "segment_index": 0,
            "distance_nm": 2145.0,
            "headwind_component_kt": 12.0,
            "tailwind_component_kt": 0.0,
            "groundspeed_kt": 171.0,
            "wind_source": "pressure_level",
            "wind_altitude_ft": 12000,
        }
    ]
    diversions = [
        {
            "airport": {"icao_code": "KPHX", "name": "Phoenix Sky Harbor", "longest_runway_ft": 11489},
            "distance_from_route_nm": 35.2,
        }
    ]
    dep = {"icao_code": "KJFK", "ident": "KJFK", "name": "JFK"}
    dest = {"icao_code": "KLAX", "ident": "KLAX", "name": "LAX"}
    aircraft = {"name": "Cirrus SR22", "cruise_speed_kt": 183, "cruise_altitude_ft": 12000}
    return route, request, segments, diversions, dep, dest, aircraft


class TestCopilotContext:
    async def test_build_route_context_includes_key_fields(self, sample_route_data):
        route, request, segments, diversions, dep, dest, aircraft = sample_route_data
        ctx = await build_route_context(
            route, request, segments, diversions, dep, dest, aircraft, refresh_live_weather=False
        )
        assert ctx["departure"]["icao"] == "KJFK"
        assert ctx["destination"]["icao"] == "KLAX"
        assert "runway_suitability" in ctx
        assert "planning_economics" in ctx
        assert "ml_predictions" in ctx
        assert ctx["primary_route"]["score"] == 82.0
        assert len(ctx["segments"]["primary"]) == 1
        assert ctx["diversions"][0]["icao"] == "KPHX"
        assert "comparison" in ctx
        assert "quick_facts" in ctx
        assert ctx["quick_facts"]["departure_icao"] == "KJFK"


class TestCopilotLLM:
    async def test_answer_with_llm_calls_gemini(self, sample_route_data):
        route, request, segments, diversions, dep, dest, aircraft = sample_route_data
        ctx = await build_route_context(
            route, request, segments, diversions, dep, dest, aircraft, refresh_live_weather=False
        )

        mock_response = AsyncMock()
        mock_response.is_error = False
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Primary route scored 82 due to balanced preference."}
                        ]
                    }
                }
            ]
        }

        with patch("app.services.copilot.settings") as mock_settings:
            mock_settings.copilot_enabled = True
            mock_settings.gemini_api_key = "gemini-test-key"
            mock_settings.gemini_model = "gemini-2.5-flash-lite"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client

                answer, sources = await answer_with_llm(ctx, "Why was this route selected?")

        assert "82" in answer
        assert "route_context_bundle" in sources
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args.kwargs
        assert "generativelanguage.googleapis.com" in mock_client.post.call_args.args[0]
        assert call_kwargs["params"]["key"] == "gemini-test-key"

    def test_suggested_questions_count(self):
        assert len(SUGGESTED_QUESTIONS) >= 5


class TestFAAParser:
    def test_unknown_on_none_payload(self):
        status = parse_faa_airport_status("KJFK", None)
        assert status.status == "unknown"
        assert status.parse_success is False
