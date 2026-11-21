"""CORS: only the configured origins may call the API from a browser."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, cors_options

PREFLIGHT_HEADERS = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


def _client_for_current_settings() -> TestClient:
    probe = FastAPI()
    probe.add_middleware(CORSMiddleware, **cors_options())

    @probe.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(probe)


@pytest.fixture
def exact_origins(monkeypatch):
    monkeypatch.setattr(settings, "api_cors_origins", "http://localhost:3000,https://aeroroute.example.com")
    monkeypatch.setattr(settings, "api_cors_origin_regex", "")


def test_configured_origin_is_allowed(exact_origins):
    response = _client_for_current_settings().options(
        "/ping", headers={"Origin": "https://aeroroute.example.com", **PREFLIGHT_HEADERS}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://aeroroute.example.com"


@pytest.mark.parametrize("origin", ["https://evil.vercel.app", "https://aeroroute.example.com.evil.io", "http://localhost:3001"])
def test_other_origins_are_rejected(exact_origins, origin):
    response = _client_for_current_settings().options("/ping", headers={"Origin": origin, **PREFLIGHT_HEADERS})
    assert "access-control-allow-origin" not in response.headers


def test_any_vercel_app_is_not_allowed_by_default(exact_origins):
    response = _client_for_current_settings().get("/ping", headers={"Origin": "https://attacker-project.vercel.app"})
    assert "access-control-allow-origin" not in response.headers


def test_optional_regex_allows_only_matching_origins(monkeypatch):
    monkeypatch.setattr(settings, "api_cors_origins", "https://aeroroute.example.com")
    monkeypatch.setattr(settings, "api_cors_origin_regex", r"^https://aeroroute-[a-z0-9-]+-me\.vercel\.app$")
    client = _client_for_current_settings()
    good = client.get("/ping", headers={"Origin": "https://aeroroute-git-feature-me.vercel.app"})
    bad = client.get("/ping", headers={"Origin": "https://evil.vercel.app"})
    assert good.headers["access-control-allow-origin"] == "https://aeroroute-git-feature-me.vercel.app"
    assert "access-control-allow-origin" not in bad.headers


def test_credentials_are_not_enabled(exact_origins):
    response = _client_for_current_settings().get("/ping", headers={"Origin": "https://aeroroute.example.com"})
    assert "access-control-allow-credentials" not in response.headers


def test_unexpected_request_headers_are_rejected(exact_origins):
    response = _client_for_current_settings().options(
        "/ping",
        headers={
            "Origin": "https://aeroroute.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-evil-header",
        },
    )
    assert response.status_code == 400


def test_the_real_app_uses_the_same_policy():
    assert cors_options()["allow_credentials"] is False
    assert any(middleware.cls is CORSMiddleware for middleware in app.user_middleware)
