from __future__ import annotations

from app.utils.ttl_cache import MISSING, TTLCache


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_value_is_returned_until_it_expires():
    clock = _Clock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    cache.set("k", "v")
    clock.now = 9.9
    assert cache.get("k") == "v"
    clock.now = 10.0
    assert cache.get("k") is MISSING
    assert len(cache) == 0


def test_missing_key_returns_default():
    cache = TTLCache(ttl_seconds=10)
    assert cache.get("nope") is MISSING
    assert cache.get("nope", default=None) is None


def test_none_values_can_be_cached():
    cache = TTLCache(ttl_seconds=10)
    cache.set("k", None)
    assert cache.get("k") is None


def test_oldest_entries_are_evicted_beyond_capacity():
    cache = TTLCache(ttl_seconds=10, max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is MISSING
    assert cache.get("b") == 2 and cache.get("c") == 3


def test_overwriting_refreshes_the_ttl():
    clock = _Clock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    cache.set("k", 1)
    clock.now = 8
    cache.set("k", 2)
    clock.now = 15
    assert cache.get("k") == 2


def test_clear():
    cache = TTLCache(ttl_seconds=10)
    cache.set("k", 1)
    cache.clear()
    assert cache.get("k") is MISSING
