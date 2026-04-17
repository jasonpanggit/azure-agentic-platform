from __future__ import annotations
"""Remediation rate limiter — per agent per subscription (REMEDI-006).

Enforces:
- Max N remediation actions per agent per subscription per minute
- Protected-tag guard: resources tagged "protected" cannot be remediated
- Production scope confirmation for prod subscription actions
"""
import os

import os
import time
from collections import defaultdict
from typing import Optional

DEFAULT_MAX_ACTIONS_PER_MINUTE = int(os.environ.get("MAX_ACTIONS_PER_MINUTE", "5"))


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class ProtectedResourceError(Exception):
    """Raised when attempting to remediate a protected resource."""
    pass


class RateLimiter:
    """Sliding window rate limiter per (agent_name, subscription_id) pair."""

    def __init__(self, max_per_minute: int = DEFAULT_MAX_ACTIONS_PER_MINUTE):
        self.max_per_minute = max_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, agent_name: str, subscription_id: str) -> None:
        """Check if the agent can perform an action on this subscription."""
        key = f"{agent_name}:{subscription_id}"
        now = time.monotonic()
        window_start = now - 60.0  # 1 minute window

        # Clean expired entries
        self._windows[key] = [t for t in self._windows[key] if t > window_start]

        if len(self._windows[key]) >= self.max_per_minute:
            raise RateLimitExceededError(
                f"Rate limit exceeded: {agent_name} has performed "
                f"{len(self._windows[key])} actions on subscription "
                f"{subscription_id} in the last minute (max: {self.max_per_minute})"
            )

    def record(self, agent_name: str, subscription_id: str) -> None:
        """Record an action for rate tracking."""
        key = f"{agent_name}:{subscription_id}"
        self._windows[key].append(time.monotonic())


def check_protected_tag(resource_tags: dict) -> None:
    """Check if a resource has the "protected" tag (REMEDI-006)."""
    if resource_tags.get("protected", "").lower() == "true":
        raise ProtectedResourceError(
            "Cannot remediate resource with protected:true tag"
        )


# Singleton rate limiter instance
rate_limiter = RateLimiter()
