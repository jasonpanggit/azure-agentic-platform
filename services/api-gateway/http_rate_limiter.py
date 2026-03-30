"""Per-IP HTTP rate limiter for the API gateway (CONCERNS 1.5).

Uses a sliding window (1 minute) with in-memory storage per IP address.
This is separate from rate_limiter.py which is a per-agent remediation guard (REMEDI-006).

Limits applied in main.py:
  /api/v1/chat      — 10 req/min per IP
  /api/v1/incidents — 30 req/min per IP
"""
from __future__ import annotations

import os
import time
from collections import defaultdict

DEFAULT_CHAT_LIMIT = int(os.environ.get("HTTP_RATE_LIMIT_CHAT", "10"))
DEFAULT_INCIDENTS_LIMIT = int(os.environ.get("HTTP_RATE_LIMIT_INCIDENTS", "30"))


class HttpRateLimiter:
    """Sliding window per-IP rate limiter."""

    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _clean(self, ip: str) -> None:
        """Remove timestamps older than 1 minute."""
        window_start = time.monotonic() - 60.0
        self._windows[ip] = [t for t in self._windows[ip] if t > window_start]

    def check(self, ip: str) -> bool:
        """Return True if request is allowed and record it. Return False if rate limited."""
        self._clean(ip)
        if len(self._windows[ip]) >= self.max_per_minute:
            return False
        self._windows[ip].append(time.monotonic())
        return True

    def retry_after(self, ip: str) -> int:
        """Seconds until oldest request in window expires (for Retry-After header)."""
        self._clean(ip)
        if not self._windows[ip]:
            return 0
        oldest = min(self._windows[ip])
        remaining = 60.0 - (time.monotonic() - oldest)
        return max(1, int(remaining) + 1)


# Module-level instances — configured via environment variables
chat_rate_limiter = HttpRateLimiter(max_per_minute=DEFAULT_CHAT_LIMIT)
incidents_rate_limiter = HttpRateLimiter(max_per_minute=DEFAULT_INCIDENTS_LIMIT)
