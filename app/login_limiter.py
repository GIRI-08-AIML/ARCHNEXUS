"""Limits repeated failed sign-ins, so passwords cannot be guessed at full speed.

Two counters, both over a sliding window:
- per (client address, email): a handful of wrong passwords for one account from one place
- per client address: many failures across different accounts (password spraying)

Keying on the client address as well as the email means a stranger cannot lock you out of your own
account just by typing your email wrong from somewhere else.

State lives in this process's memory. It resets when the server restarts, and each server process
counts separately. Behind a reverse proxy, every request may appear to come from the proxy's address,
so set the proxy up to pass the real client address before relying on the per-address limit.
"""
import threading
import time
from collections import defaultdict, deque


class LoginLimiter:
    MAX_KEYS = 10_000  # bound memory if someone sprays many different emails

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque] = defaultdict(deque)

    @staticmethod
    def _keys(ip: str, email: str) -> tuple[str, str]:
        return f"acct|{ip}|{email}", f"ip|{ip}"

    def _recent(self, key: str, window: float, now: float) -> deque:
        q = self._failures[key]
        while q and now - q[0] >= window:
            q.popleft()
        return q

    def blocked_for(self, ip: str, email: str, *, max_per_account: int, max_per_ip: int, window: float) -> int:
        """Seconds the caller must wait, or 0 if the sign-in may proceed."""
        now = self.clock()
        with self._lock:
            acct_key, ip_key = self._keys(ip, email)
            waits = [0.0]
            for key, limit in ((acct_key, max_per_account), (ip_key, max_per_ip)):
                if key not in self._failures:
                    continue
                q = self._recent(key, window, now)
                if len(q) >= limit:
                    waits.append(q[0] + window - now)
            return int(max(waits)) + 1 if max(waits) > 0 else 0

    def record_failure(self, ip: str, email: str, *, window: float) -> None:
        now = self.clock()
        with self._lock:
            if len(self._failures) > self.MAX_KEYS:
                for key in list(self._failures):
                    if not self._recent(key, window, now):
                        del self._failures[key]
            for key in self._keys(ip, email):
                self._failures[key].append(now)

    def reset(self, ip: str, email: str) -> None:
        """A correct password clears that account's counter (the per-address counter keeps running)."""
        with self._lock:
            self._failures.pop(self._keys(ip, email)[0], None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginLimiter()
