"""Small thread-safe TTL cache for read-mostly, process-local data."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable

MISSING: Any = object()


class TTLCache:
    """Entries expire ``ttl_seconds`` after being set; the oldest entries are evicted beyond ``max_entries``."""

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any, default: Any = MISSING) -> Any:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return default
            expires_at, value = entry
            if expires_at <= self._clock():
                del self._items[key]
                return default
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._items[key] = (self._clock() + self._ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
