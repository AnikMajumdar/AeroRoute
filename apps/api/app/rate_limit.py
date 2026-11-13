from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Callable

from fastapi import Depends, HTTPException

from app.auth import get_current_user_id

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe sliding-window limiter, per key, held in process memory.

    State is per process: with several Modal containers the effective limit is per container. Keys whose hits
    have all left the window are dropped, so memory is bounded by the number of recently active keys.
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        window_start = now - self.window_seconds
        while hits and hits[0] <= window_start:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _evict_idle_keys(self, now: float) -> None:
        for key in list(self._hits):
            self._prune(key, now)

    def check(self, key: str) -> bool:
        """Record a hit and return True, or return False (recording nothing) when the key is over its limit."""
        now = self._clock()
        with self._lock:
            hits = self._prune(key, now)
            if hits is not None and len(hits) >= self.max_requests:
                return False
            if hits is None:
                hits = self._hits[key] = deque()
            hits.append(now)
            if len(self._hits) > self.max_keys:
                self._evict_idle_keys(now)
            return True

    def retry_after(self, key: str) -> int:
        """Whole seconds until the key may try again (0 when it is not limited)."""
        now = self._clock()
        with self._lock:
            hits = self._prune(key, now)
            if hits is None or len(hits) < self.max_requests:
                return 0
            return max(1, math.ceil(hits[0] + self.window_seconds - now))

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def reset_all_limiters() -> None:
    """Clear every application limiter (used by tests)."""
    for limiter in _APPLICATION_LIMITERS:
        limiter.reset()


def rate_limited(limiter: RateLimiter) -> Callable[..., None]:
    """Route dependency: authenticate first (401 never consumes quota), then enforce ``limiter`` per user."""

    async def dependency(user_id: str = Depends(get_current_user_id)) -> None:
        if not limiter.check(user_id):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded — try again shortly",
                headers={"Retry-After": str(limiter.retry_after(user_id))},
            )

    return dependency


route_calculate_limiter = RateLimiter(max_requests=10, window_seconds=60)
copilot_chat_limiter = RateLimiter(max_requests=10, window_seconds=60)
brief_draft_limiter = RateLimiter(max_requests=10, window_seconds=60)
live_data_refresh_limiter = RateLimiter(max_requests=6, window_seconds=60)
aircraft_create_limiter = RateLimiter(max_requests=20, window_seconds=3600)

_APPLICATION_LIMITERS = [
    route_calculate_limiter,
    copilot_chat_limiter,
    brief_draft_limiter,
    live_data_refresh_limiter,
    aircraft_create_limiter,
]
