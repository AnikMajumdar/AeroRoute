"""The Gemini API key must never appear in a URL or in application logs."""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.logging_config import configure_logging
from app.services import copilot

SECRET = "AIzaSy_TEST_SECRET_KEY_DO_NOT_LEAK"


async def test_gemini_key_is_sent_as_header_and_never_logged(monkeypatch, caplog):
    monkeypatch.setattr(settings, "gemini_api_key", SECRET)
    configure_logging("INFO")
    caplog.set_level(logging.DEBUG)
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["header"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text, _model = await copilot._call_gemini_model(client, "gemini-2.5-flash-lite", {"contents": []})

    assert text == "ok"
    assert seen["header"] == SECRET
    assert SECRET not in (seen["url"] or "")
    assert SECRET not in caplog.text


def test_http_client_loggers_do_not_emit_request_urls():
    configure_logging("INFO")
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
