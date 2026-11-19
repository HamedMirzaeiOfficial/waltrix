"""In-process sliding-window rate limiter.

Good enough for a single API process. With several replicas, each replica
enforces its own window (documented limitation); swap ``RateLimiter`` for a
Redis-backed implementation with the same interface to share state. Redis
would only hold counters: it is never a source of financial truth.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        """Record a hit. Returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self._max_keys:
                    self._evict(now, window)
                q = self._hits[key] = deque()
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(q[0] + window - now) + 1)
            q.append(now)
            return True, 0

    def _evict(self, now: float, window: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= now - window]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:  # still full: drop the oldest half
            for k in list(self._hits)[: self._max_keys // 2]:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
