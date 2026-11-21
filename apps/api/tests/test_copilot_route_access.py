"""Copilot endpoints: unknown or foreign routes answer 404 (not 500) and never run a tool."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import copilot_tools
from tests.fakes import seed_route

MISSING_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _enable_copilot(monkeypatch):
    monkeypatch.setattr(settings, "copilot_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


@pytest.fixture
def tool_calls(monkeypatch):
    """Replace the tools the 'unknown' intent would run with spies that record their calls."""
    calls: list[tuple] = []

    async def spy(*args, **_kwargs):
        calls.append(args)
        return {"source": "spy"}

    monkeypatch.setattr(copilot_tools, "get_route_summary", spy)
    monkeypatch.setattr(copilot_tools, "get_route_score_explanation", spy)
    return calls


def _chat(api, route_id: str, question: str = "hello"):
    return api.client.post(f"/routes/{route_id}/copilot/chat", json={"question": question})


class TestChatRouteAccess:
    def test_unknown_route_is_404_not_500(self, api, tool_calls):
        response = _chat(api, MISSING_ID)
        assert response.status_code == 404
        assert response.json()["detail"] == "Route not found"

    def test_unknown_route_runs_no_tool_and_stores_nothing(self, api, tool_calls):
        _chat(api, MISSING_ID)
        assert tool_calls == []
        assert api.db.rows("route_briefs") == []

    def test_other_users_route_is_404_and_runs_no_tool(self, api, tool_calls):
        ids = seed_route(api.db, user_id="user_B")
        response = _chat(api, ids["result_id"])
        assert response.status_code == 404
        assert tool_calls == []
        assert api.db.rows("route_briefs") == []

    def test_own_route_still_works(self, api, tool_calls, monkeypatch):
        async def fake_llm(*_args, **_kwargs):
            return "Looks fine.", ["spy"]

        monkeypatch.setattr("app.routers.routes.answer_with_llm", fake_llm)
        ids = seed_route(api.db, user_id="user_A")
        response = _chat(api, ids["result_id"])
        assert response.status_code == 200
        assert response.json()["answer"] == "Looks fine."
        assert tool_calls, "the intent's tools should run for an owned route"
        (brief,) = api.db.rows("route_briefs")
        assert brief["brief_type"] == "llm_chat"

    def test_unexpected_context_failure_is_still_a_generic_500(self, api, tool_calls, monkeypatch):
        async def explode(*_args, **_kwargs):
            raise Exception("database exploded")

        monkeypatch.setattr("app.services.route_context_bundle.get_route_context", explode)
        ids = seed_route(api.db, user_id="user_A")
        response = _chat(api, ids["result_id"])
        assert response.status_code == 500
        assert response.json()["detail"] == "Could not load route context"
        assert tool_calls == []


class TestOtherCopilotRoutes:
    def test_suggestions_for_unknown_route_is_404(self, api):
        assert api.client.get(f"/routes/{MISSING_ID}/copilot/suggestions").status_code == 404

    def test_suggestions_for_other_users_route_is_404(self, api):
        ids = seed_route(api.db, user_id="user_B")
        assert api.client.get(f"/routes/{ids['result_id']}/copilot/suggestions").status_code == 404

    def test_brief_draft_for_unknown_route_is_404(self, api):
        assert api.client.post(f"/routes/{MISSING_ID}/brief/draft").status_code == 404
