from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import DefaultDict

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter for route calculations."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: DefaultDict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window_seconds
        hits = [t for t in self._hits[key] if t > window_start]
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


route_calculate_limiter = RateLimiter(max_requests=10, window_seconds=60)
