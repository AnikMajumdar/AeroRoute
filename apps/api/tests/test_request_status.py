"""Every route calculation must leave the 'processing' state: completed, or failed with its partial output removed."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.routers import routes as routes_module
from app.schemas import RouteCalculateRequest
from app.services.request_status import STALE_MESSAGE, expire_stale_requests, mark_request_failed
from tests.fakes import calculation_env, seed_route

REFERENCE_DETAIL = re.compile(r"Route calculation failed \(reference ([0-9a-f]{8})\)")


def _inject(db, table: str, operation: str, behaviour) -> None:
    """Make ``db.table(table).<operation>(...).execute()`` call ``behaviour(query)`` instead of working."""
    real_table = db.table

    def table_with_fault(name):
        query = real_table(name)
        if name == table:
            real_execute = query.execute

            def execute():
                return behaviour(query) if query._op == operation else real_execute()

            query.execute = execute
        return query

    db.table = table_with_fault


def _raise(exc: Exception):
    def behaviour(_query):
        raise exc

    return behaviour


def _empty_result(_query):
    return SimpleNamespace(data=[], count=None)


@pytest.fixture
def env(api, monkeypatch):
    return calculation_env(api, monkeypatch)


class TestSuccessfulCalculation:
    def test_request_is_completed_and_keeps_its_result(self, env):
        response = env.post()
        assert response.status_code == 201
        (request,) = env.db.rows("route_requests")
        assert request["status"] == "completed"
        assert len(env.db.rows("route_results")) == 1


class TestFailureLeavesNoProcessingRequest:
    def test_failed_result_save_marks_the_request_failed(self, env):
        # used to raise HTTPException straight through `except HTTPException: raise`, leaving 'processing'
        _inject(env.db, "route_results", "insert", _empty_result)
        response = env.post()
        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to save route result"
        (request,) = env.db.rows("route_requests")
        assert request["status"] == "failed"
        assert request["error_message"] == "Failed to save route result"

    def test_failure_after_partial_writes_removes_the_partial_result(self, env):
        _inject(env.db, "route_segments", "insert", _raise(RuntimeError("db hiccup")))
        response = env.post()
        assert response.status_code == 500
        reference = REFERENCE_DETAIL.fullmatch(response.json()["detail"]).group(1)
        (request,) = env.db.rows("route_requests")
        assert request["status"] == "failed"
        assert request["error_message"] == f"RuntimeError (reference {reference})"
        assert env.db.rows("route_results") == [], "a failed request must not keep a half-written result"

    def test_a_failing_status_update_does_not_mask_the_original_error(self, env):
        _inject(env.db, "route_segments", "insert", _raise(RuntimeError("db hiccup")))
        _inject(env.db, "route_requests", "update", _raise(Exception("database is down")))
        response = env.post()
        assert response.status_code == 500
        assert REFERENCE_DETAIL.fullmatch(response.json()["detail"])

    async def test_cancelled_calculation_is_marked_failed(self, env, monkeypatch):
        async def cancelled(**_kwargs):
            raise asyncio.CancelledError

        monkeypatch.setattr("app.routers.routes.route_calculator.calculate", cancelled)
        body = RouteCalculateRequest(**env.payload)
        with pytest.raises(asyncio.CancelledError):
            await routes_module.calculate_route(body, user_id="user_A")
        (request,) = env.db.rows("route_requests")
        assert request["status"] == "failed"
        assert "Cancelled" in request["error_message"]


class TestStaleRequests:
    @staticmethod
    def _row(row_id: str, user_id: str, status: str, minutes_old: int) -> dict:
        created = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
        return {"id": row_id, "user_id": user_id, "status": status, "created_at": created.isoformat()}

    def test_new_calculation_expires_the_users_stale_requests_only(self, env, monkeypatch):
        env.db.tables["route_requests"] = [
            self._row("stale", "user_A", "processing", 11),
            self._row("fresh", "user_A", "processing", 2),
            self._row("other-user", "user_B", "processing", 30),
            self._row("done", "user_A", "completed", 60),
        ]

        async def stop(**_kwargs):
            raise RuntimeError("stop here")

        monkeypatch.setattr("app.routers.routes.route_calculator.calculate", stop)
        env.post()

        by_id = {row["id"]: row for row in env.db.rows("route_requests")}
        assert by_id["stale"]["status"] == "failed"
        assert by_id["stale"]["error_message"] == STALE_MESSAGE
        assert by_id["fresh"]["status"] == "processing"
        assert by_id["other-user"]["status"] == "processing"
        assert by_id["done"]["status"] == "completed"

    def test_expiry_lookup_failure_does_not_block_a_calculation(self, env):
        _inject(env.db, "route_requests", "select", _raise(Exception("database is down")))
        assert env.post().status_code == 201

    def test_expiry_removes_the_partial_result_of_a_stale_request(self, env):
        env.db.tables["route_requests"] = [self._row("stale", "user_A", "processing", 11)]
        env.db.tables["route_results"] = [{"id": "partial-result", "route_request_id": "stale"}]
        expire_stale_requests(env.db, "user_A")
        assert env.db.rows("route_requests")[0]["status"] == "failed"
        assert env.db.rows("route_results") == []

    def test_listing_routes_expires_stale_requests_and_hides_their_partial_result(self, env):
        ids = seed_route(env.db, user_id="user_A")
        env.db.tables["route_requests"].append(self._row("stale", "user_A", "processing", 11))
        env.db.tables["route_results"].append({"id": "partial-result", "route_request_id": "stale"})

        response = env.client.get("/routes")

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [ids["result_id"]]
        by_id = {row["id"]: row for row in env.db.rows("route_requests")}
        assert by_id["stale"]["status"] == "failed"
        assert [row["id"] for row in env.db.rows("route_results")] == [ids["result_id"]]


class TestHelpersNeverRaise:
    class _BrokenDb:
        def table(self, _name):
            raise Exception("database is down")

    def test_mark_request_failed(self):
        mark_request_failed(self._BrokenDb(), "some-id", "boom")

    def test_expire_stale_requests(self):
        expire_stale_requests(self._BrokenDb(), "user_A")
