"""Missing rows must yield 404 (not 500): postgrest's maybe_single() returns None when nothing matches."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.fakes import FakeSupabase, make_aircraft, make_airport, make_id, seed_route

MISSING_ID = "00000000-0000-0000-0000-000000000000"


def _departure_soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


class TestFetchOne:
    def test_returns_first_row(self):
        from app.db_utils import fetch_one

        db = FakeSupabase({"airports": [make_airport("KJFK"), make_airport("KLAX")]})
        row = fetch_one(db.table("airports").select("*").eq("icao_code", "KLAX"))
        assert row is not None and row["icao_code"] == "KLAX"

    def test_returns_none_when_nothing_matches(self):
        from app.db_utils import fetch_one

        assert fetch_one(FakeSupabase().table("airports").select("*").eq("icao_code", "KXXX")) is None

    def test_fake_reproduces_the_postgrest_quirk(self):
        # maybe_single().execute() returns None for zero rows - the behaviour that used to crash callers.
        assert FakeSupabase().table("airports").select("*").maybe_single().execute() is None


class TestGetRoute:
    def test_unknown_route_is_404_not_500(self, api):
        response = api.client.get(f"/routes/{MISSING_ID}")
        assert response.status_code == 404

    def test_malformed_route_id_is_422(self, api):
        response = api.client.get("/routes/not-a-uuid")
        assert response.status_code == 422

    def test_other_users_route_is_404(self, api):
        ids = seed_route(api.db, user_id="user_B")
        response = api.client.get(f"/routes/{ids['result_id']}")
        assert response.status_code == 404

    def test_own_route_is_returned(self, api):
        ids = seed_route(api.db, user_id="user_A")
        response = api.client.get(f"/routes/{ids['result_id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == ids["result_id"]
        assert body["departure_airport"]["icao_code"] == "KJFK"
        assert body["fuel_price_usd_per_gal"] == 6.5

    def test_route_with_missing_airport_row_is_reported_as_incomplete(self, api):
        ids = seed_route(api.db, user_id="user_A")
        api.db.tables["airports"] = [a for a in api.db.tables["airports"] if a["id"] != ids["dest_id"]]
        response = api.client.get(f"/routes/{ids['result_id']}")
        assert response.status_code == 500
        assert response.json()["detail"] == "Route data is incomplete"


class TestListRoutes:
    def test_lists_only_own_routes_and_skips_incomplete_rows(self, api):
        own = seed_route(api.db, user_id="user_A")
        seed_route(api.db, user_id="user_B")
        # a request without a result row (e.g. still processing) must be skipped, not crash
        api.db.tables["route_requests"].append(
            {
                "id": make_id(),
                "user_id": "user_A",
                "departure_airport_id": own["dep_id"],
                "destination_airport_id": own["dest_id"],
                "aircraft_profile_id": own["aircraft_id"],
                "status": "processing",
                "created_at": "2026-11-13T13:00:00+00:00",
            }
        )
        response = api.client.get("/routes")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [own["result_id"]]


class TestCalculateRouteLookups:
    def _body(self, **overrides):
        body = {
            "departure_airport_id": make_id(),
            "destination_airport_id": make_id(),
            "aircraft_profile_id": make_id(),
            "departure_time": _departure_soon(),
            "fuel_price_usd_per_gal": 6.5,
        }
        body.update(overrides)
        return body

    def test_unknown_departure_airport_is_404(self, api):
        api.db.tables["airports"] = [make_airport("KLAX")]
        response = api.client.post("/routes/calculate", json=self._body())
        assert response.status_code == 404
        assert response.json()["detail"] == "Departure airport not found"

    def test_malformed_ids_are_422(self, api):
        response = api.client.post("/routes/calculate", json=self._body(departure_airport_id="nope"))
        assert response.status_code == 422

    def test_unknown_aircraft_is_404(self, api):
        dep, dest = make_airport("KJFK"), make_airport("KLAX")
        api.db.tables["airports"] = [dep, dest]
        body = self._body(
            departure_airport_id=dep["id"],
            destination_airport_id=dest["id"],
        )
        response = api.client.post("/routes/calculate", json=body)
        assert response.status_code == 404
        assert response.json()["detail"] == "Aircraft profile not found"


class TestCopilotRouteLookups:
    def test_suggestions_for_unknown_route_are_404(self, api):
        assert api.client.get(f"/routes/{MISSING_ID}/copilot/suggestions").status_code == 404

    def test_brief_for_unknown_route_is_404(self, api):
        assert api.client.post(f"/routes/{MISSING_ID}/brief/draft").status_code == 404

    def test_live_refresh_for_unknown_route_is_404(self, api):
        assert api.client.post(f"/routes/{MISSING_ID}/live-data/refresh").status_code == 404


def test_aircraft_factory_defaults():
    assert make_aircraft()["is_preset"] is True
