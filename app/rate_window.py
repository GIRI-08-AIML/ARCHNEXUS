"""A small in-memory limit on how often something can happen per key (for example per user).

Like the login limiter, the counts live in this process's memory: they reset when the server
restarts, and each server process counts separately.
"""
import threading
import time
from collections import defaultdict, deque


class RateWindow:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)

    def try_hit(self, key: str, limit: int, window: float) -> int:
        """Record one use. Returns 0 if allowed, otherwise the seconds to wait. A limit of 0 means no limit."""
        if limit <= 0:
            return 0
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return int(q[0] + window - now) + 1
            q.append(now)
            return 0

    def undo(self, key: str) -> None:
        """Give back the most recent use (the call it was counted for did not go through)."""
        with self._lock:
            q = self._hits.get(key)
            if q:
                q.pop()
                if not q:
                    del self._hits[key]

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


chat_limiter = RateWindow()
