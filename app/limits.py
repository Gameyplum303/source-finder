"""Bounded in-memory cache and rate limiter shared by search and AI review.

Both are capped in size so a flood of distinct keys (queries, IPs) cannot
exhaust memory. They are per-process; run one worker, or swap in Redis, if you
scale out.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    """LRU cache whose entries expire after a per-entry time-to-live."""

    def __init__(self, max_items: int, ttl: float):
        self.max_items, self.ttl = max_items, ttl
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: V, ttl: float | None = None) -> None:
        self._data[key] = (time.monotonic() + (self.ttl if ttl is None else ttl), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


class RateLimiter:
    """Sliding-window limit of `limit` events per `window` seconds, per key."""

    MAX_KEYS = 10_000

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > self.MAX_KEYS:  # drop idle clients
            for idle in [k for k, h in self._hits.items() if not h or now - h[-1] > self.window]:
                del self._hits[idle]
        return True
