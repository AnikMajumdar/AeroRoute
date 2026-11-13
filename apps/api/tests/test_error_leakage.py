"""Internal error details (exceptions, config hints, provider messages) must not reach clients or the database."""

from __future__ import annotations

import importlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import settings
from app.services import copilot, copilot_intent, copilot_tools
from tests.fakes import make_aircraft, make_airport

# The live_data package re-exports an instance under the orchestrator's module name, so import by path.
orchestrator_module = importlib.import_module("app.services.live_data.live_data_orchestrator")
notam_module = importlib.import_module("app.services.live_data.notam_provider")

SECRET = "postgres://admin:hunter2@internal-db.example:5432/prod"


def _response(status: int, body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://example.test/v1"))


class TestRouteCalculationFailure:
    def _calculate(self, api, monkeypatch):
        dep, dest = make_airport("KJFK"), make_airport("KLAX")
        aircraft = make_aircraft()
        api.db.tables["airports"] = [dep, dest]
        api.db.tables["aircraft_profiles"] = [aircraft]

        async def explode(**_kwargs):
            raise RuntimeError(f"connection to {SECRET} failed")

        monkeypatch.setattr("app.routers.routes.route_calculator.calculate", explode)
        return api.client.post(
            "/routes/calculate",
            json={
                "departure_airport_id": dep["id"],
                "destination_airport_id": dest["id"],
                "aircraft_profile_id": aircraft["id"],
                "departure_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                "fuel_price_usd_per_gal": 6.5,
            },
        )

    def test_client_gets_a_reference_not_the_exception(self, api, monkeypatch):
        response = self._calculate(api, monkeypatch)
        assert response.status_code == 500
        assert re.fullmatch(r"Route calculation failed \(reference [0-9a-f]{8}\)", response.json()["detail"])
        assert "hunter2" not in response.text

    def test_stored_error_message_has_no_exception_text(self, api, monkeypatch):
        response = self._calculate(api, monkeypatch)
        reference = re.search(r"reference ([0-9a-f]{8})", response.json()["detail"]).group(1)
        (row,) = api.db.rows("route_requests")
        assert row["status"] == "failed"
        assert row["error_message"] == f"RuntimeError (reference {reference})"
        assert "hunter2" not in json.dumps(row)

    def test_full_exception_is_logged_with_the_reference(self, api, monkeypatch, caplog):
        with caplog.at_level(logging.ERROR, logger="app.routers.routes"):
            response = self._calculate(api, monkeypatch)
        reference = re.search(r"reference ([0-9a-f]{8})", response.json()["detail"]).group(1)
        assert reference in caplog.text
        assert "hunter2" in caplog.text  # operators keep the details


class TestGeminiErrors:
    @pytest.mark.parametrize(
        ("status", "body", "expected"),
        [
            (429, {"error": {"message": "Quota exceeded for project my-secret-project, limit: 0"}}, "usage limit"),
            (429, {"error": {"message": "Too many requests"}}, "busy"),
            (404, {"error": {"message": "models/gemini-x is not found for project my-secret-project"}}, "not available"),
            (401, {"error": {"message": "API key not valid: AIzaSyFAKE"}}, "not configured correctly"),
            (403, {"error": {"message": "permission denied for my-secret-project"}}, "not configured correctly"),
            (500, {"error": {"message": "internal failure in my-secret-project"}}, "HTTP 500"),
        ],
    )
    def test_user_message_is_generic(self, status, body, expected):
        message = copilot._parse_gemini_error(_response(status, body))
        assert expected in message
        for forbidden in ("GEMINI_", ".env", "apps/api", "my-secret-project", "AIza", "AI Studio"):
            assert forbidden not in message

    def test_unparsable_body_is_handled(self):
        response = httpx.Response(502, text="<html>bad gateway</html>", request=httpx.Request("POST", "https://x"))
        assert copilot._parse_gemini_error(response) == "The AI service returned an error (HTTP 502)."

    def test_provider_message_is_kept_in_the_log(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.services.copilot"):
            copilot._parse_gemini_error(_response(404, {"error": {"message": "models/x not found for my-secret-project"}}))
        assert "my-secret-project" in caplog.text

    def test_blocked_prompt_message_is_generic(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.services.copilot"):
            with pytest.raises(RuntimeError) as exc:
                copilot._extract_gemini_text({"promptFeedback": {"blockReason": "SAFETY_INTERNAL_CODE"}})
        assert "SAFETY_INTERNAL_CODE" not in str(exc.value)
        assert "SAFETY_INTERNAL_CODE" in caplog.text

    async def test_unexpected_transport_error_is_generic(self, monkeypatch):
        monkeypatch.setattr(settings, "copilot_enabled", True)
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")

        class ExplodingClient:
            def __init__(self, *_args, **_kwargs):
                raise ConnectionError(f"cannot reach {SECRET}")

        monkeypatch.setattr(copilot.httpx, "AsyncClient", ExplodingClient)
        with pytest.raises(RuntimeError) as exc:
            await copilot.answer_with_llm({"quick_facts": {}}, "Why?")
        assert str(exc.value) == "The AI service is currently unavailable."


class TestCopilotEndpoint:
    @pytest.fixture(autouse=True)
    def _enable_copilot(self, monkeypatch):
        monkeypatch.setattr(settings, "copilot_enabled", True)
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    def test_disabled_message_has_no_configuration_hints(self, api, monkeypatch):
        monkeypatch.setattr(settings, "copilot_enabled", False)
        response = api.client.post(
            "/routes/00000000-0000-0000-0000-000000000000/copilot/chat", json={"question": "hello"}
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "AeroRoute Copilot is not enabled."

    def test_context_failure_does_not_leak_the_exception(self, api, monkeypatch):
        async def explode(*_args, **_kwargs):
            raise Exception(f"db password in {SECRET}")

        monkeypatch.setattr("app.routers.routes.build_intent_context", explode)
        response = api.client.post(
            "/routes/00000000-0000-0000-0000-000000000000/copilot/chat", json={"question": "hello"}
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "Could not load route context"


class TestToolAndProviderErrors:
    async def test_failed_copilot_tool_is_reported_generically(self, monkeypatch):
        async def explode(*_args, **_kwargs):
            raise Exception(f"tool failure at {SECRET}")

        async def base_context(*_args, **_kwargs):
            return {"quick_facts": {}, "limitations": [], "data_source_timestamps": {}, "warnings": []}

        monkeypatch.setattr(copilot_tools, "get_route_summary", explode)
        monkeypatch.setattr(copilot_tools, "get_route_score_explanation", explode)
        monkeypatch.setattr("app.services.route_context_bundle.get_route_context", base_context)

        _intent, context, _sources = await copilot_intent.build_intent_context(None, "route", "user", "tell me about this route")
        assert "hunter2" not in json.dumps(context)
        assert all(result["error"] == "unavailable" for result in context["tool_results"].values() if isinstance(result, dict) and "error" in result)

    async def test_failed_live_data_provider_is_reported_generically(self, monkeypatch):
        async def explode(*_args, **_kwargs):
            raise Exception(f"tfr feed failure {SECRET}")

        monkeypatch.setattr(orchestrator_module.tfr_provider, "get_tfrs_for_route", explode)
        snapshot, _timings = await orchestrator_module.live_data_orchestrator.build_snapshot(
            route_id=None, departure_icao="KJFK", destination_icao="KLAX", route_path=[], supabase=None
        )
        assert "tfrs: provider error" in snapshot.warnings
        assert "hunter2" not in json.dumps(snapshot.warnings)

    async def test_notam_http_failure_is_reported_generically(self, monkeypatch):
        class DummyCache:
            def get(self, _key):
                return None

            def set(self, *_args):
                return None

        class FailingClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def get(self, *_args, **_kwargs):
                raise httpx.ConnectError(f"cannot connect to {SECRET}")

        monkeypatch.setattr(settings, "faa_nms_api_base_url", "https://nms.example")
        monkeypatch.setattr(settings, "faa_nms_api_key", "k")
        monkeypatch.setattr(notam_module, "cache_service", DummyCache())
        monkeypatch.setattr(notam_module.httpx, "AsyncClient", FailingClient)

        result = await notam_module.OfficialApiNotamProvider().get_airport_notams("KJFK")
        assert result.meta.error == "NOTAM provider request failed"
        assert "hunter2" not in json.dumps(result.meta.to_dict())
