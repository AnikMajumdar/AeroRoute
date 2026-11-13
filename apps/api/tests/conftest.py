import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def api(monkeypatch):
    """TestClient with authentication overridden (``api.auth.user_id``) and the database replaced by FakeSupabase."""
    from fastapi.testclient import TestClient

    from app.auth import get_current_user_id
    from app.main import app
    from app.rate_limit import reset_all_limiters
    from tests.fakes import FakeSupabase

    reset_all_limiters()
    db = FakeSupabase()
    monkeypatch.setattr("app.routers.routes.get_supabase", lambda: db)
    state = SimpleNamespace(user_id="user_A")
    app.dependency_overrides[get_current_user_id] = lambda: state.user_id
    try:
        yield SimpleNamespace(client=TestClient(app, raise_server_exceptions=False), db=db, auth=state)
    finally:
        app.dependency_overrides.clear()
