"""GET /aircraft/presets is public, so it must be read-only and cheap."""

from __future__ import annotations

import pytest

from app.data.aircraft_presets import AIRCRAFT_PRESETS
from app.routers import routes as routes_module
from app.services.aircraft_presets import ensure_aircraft_presets
from tests.fakes import FakeSupabase, make_aircraft


@pytest.fixture(autouse=True)
def _clear_presets_cache():
    routes_module._PRESETS_CACHE.clear()
    yield
    routes_module._PRESETS_CACHE.clear()


def _preset_rows() -> list[dict]:
    return [
        make_aircraft(name=spec["name"], **{key: value for key, value in spec.items() if key not in ("name", "notes")})
        for spec in AIRCRAFT_PRESETS
    ]


def test_endpoint_performs_no_writes_when_presets_exist(api):
    api.db.tables["aircraft_profiles"] = _preset_rows()
    response = api.client.get("/aircraft/presets")
    assert response.status_code == 200
    assert len(response.json()) == len(AIRCRAFT_PRESETS)
    assert api.db.writes() == []


def test_second_request_is_served_from_the_cache(api):
    api.db.tables["aircraft_profiles"] = _preset_rows()
    api.client.get("/aircraft/presets")
    operations_after_first = len(api.db.ops)
    assert api.client.get("/aircraft/presets").status_code == 200
    assert len(api.db.ops) == operations_after_first


def test_empty_table_is_seeded_once(api):
    response = api.client.get("/aircraft/presets")
    assert response.status_code == 200
    assert len(response.json()) == len(AIRCRAFT_PRESETS)
    inserts = [op for op in api.db.writes() if op == ("aircraft_profiles", "insert")]
    assert len(inserts) == len(AIRCRAFT_PRESETS)

    writes_after_seed = len(api.db.writes())
    api.client.get("/aircraft/presets")
    assert len(api.db.writes()) == writes_after_seed


def test_ensure_aircraft_presets_skips_unchanged_rows():
    db = FakeSupabase({"aircraft_profiles": _preset_rows()})
    ensure_aircraft_presets(db)
    assert db.writes() == []


def test_ensure_aircraft_presets_updates_only_changed_rows():
    rows = _preset_rows()
    rows[0]["cruise_speed_kt"] += 7
    db = FakeSupabase({"aircraft_profiles": rows})
    ensure_aircraft_presets(db)
    assert db.writes() == [("aircraft_profiles", "update")]
    assert db.rows("aircraft_profiles")[0]["cruise_speed_kt"] == AIRCRAFT_PRESETS[0]["cruise_speed_kt"]
