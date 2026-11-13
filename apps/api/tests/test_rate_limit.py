from __future__ import annotations

import threading

import pytest

from app import rate_limit
from app.rate_limit import RateLimiter

MISSING_ID = "00000000-0000-0000-0000-000000000000"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestRateLimiter:
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60, clock=_Clock())
        assert [limiter.check("u") for _ in range(4)] == [True, True, True, False]

    def test_window_slides(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=2, window_seconds=60, clock=clock)
        assert limiter.check("u") and limiter.check("u")
        assert not limiter.check("u")
        clock.now += 61
        assert limiter.check("u")

    def test_blocked_attempts_are_not_recorded(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
        assert limiter.check("u")
        clock.now += 30
        assert not limiter.check("u")  # must not extend the penalty window
        clock.now += 31
        assert limiter.check("u")

    def test_keys_are_independent(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60, clock=_Clock())
        assert limiter.check("a") and limiter.check("b")
        assert not limiter.check("a")

    def test_retry_after(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
        assert limiter.retry_after("u") == 0
        limiter.check("u")
        clock.now += 10
        assert limiter.retry_after("u") == 50

    def test_idle_keys_are_evicted(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=5, window_seconds=60, max_keys=10, clock=clock)
        for index in range(10):
            limiter.check(f"user-{index}")
        assert limiter.tracked_keys() == 10
        clock.now += 120
        limiter.check("fresh-user-1")  # 11th key triggers the sweep
        assert limiter.tracked_keys() == 1

    def test_concurrent_checks_never_exceed_the_limit(self):
        limiter = RateLimiter(max_requests=50, window_seconds=60)
        allowed: list[bool] = []

        def hammer() -> None:
            for _ in range(25):
                allowed.append(limiter.check("shared"))

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert allowed.count(True) == 50


class TestEndpointsAreLimited:
    @pytest.mark.parametrize(
        ("method", "path", "limiter_name"),
        [
            ("post", f"/routes/{MISSING_ID}/brief/draft", "brief_draft_limiter"),
            ("post", f"/routes/{MISSING_ID}/copilot/chat", "copilot_chat_limiter"),
            ("post", f"/routes/{MISSING_ID}/live-data/refresh", "live_data_refresh_limiter"),
        ],
    )
    def test_over_limit_requests_get_429_with_retry_after(self, api, monkeypatch, method, path, limiter_name):
        limiter = getattr(rate_limit, limiter_name)
        monkeypatch.setattr(limiter, "max_requests", 2)
        kwargs = {"json": {"question": "why?"}} if path.endswith("/chat") else {}
        statuses = [getattr(api.client, method)(path, **kwargs).status_code for _ in range(3)]
        assert statuses[:2] != [429, 429]
        assert statuses[2] == 429
        blocked = getattr(api.client, method)(path, **kwargs)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1

    def test_calculate_is_limited(self, api, monkeypatch):
        monkeypatch.setattr(rate_limit.route_calculate_limiter, "max_requests", 1)
        body = {
            "departure_airport_id": MISSING_ID,
            "destination_airport_id": "11111111-1111-1111-1111-111111111111",
            "aircraft_profile_id": MISSING_ID,
            "departure_time": "2099-01-01T00:00:00Z",
            "fuel_price_usd_per_gal": 6.5,
        }
        api.client.post("/routes/calculate", json=body)
        assert api.client.post("/routes/calculate", json=body).status_code == 429

    def test_aircraft_creation_is_limited(self, api, monkeypatch):
        monkeypatch.setattr(rate_limit.aircraft_create_limiter, "max_requests", 1)
        payload = {"name": "Test", "cruise_speed_kt": 100, "fuel_burn_gph": 8}
        assert api.client.post("/aircraft", json=payload).status_code == 201
        assert api.client.post("/aircraft", json=payload).status_code == 429

    def test_limits_are_per_user(self, api, monkeypatch):
        monkeypatch.setattr(rate_limit.brief_draft_limiter, "max_requests", 1)
        path = f"/routes/{MISSING_ID}/brief/draft"
        api.auth.user_id = "user_A"
        api.client.post(path)
        assert api.client.post(path).status_code == 429
        api.auth.user_id = "user_B"
        assert api.client.post(path).status_code != 429
