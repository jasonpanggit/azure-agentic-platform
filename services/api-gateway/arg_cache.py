from __future__ import annotations
"""In-process TTL cache for ARG query results.

Eliminates redundant ARG round-trips when multiple requests arrive within
a short window. No external dependencies — stores results in a module-level
dict keyed by (cache_key, frozenset(subscription_ids)).

Usage::

    from services.api_gateway.arg_cache import get_cached

    findings = get_cached(
        key="cert_expiry",
        subscription_ids=subscription_ids,
        ttl_seconds=3600,
        fetch_fn=lambda: scan_cert_expiry(credential, subscription_ids),
    )

Cache is intentionally process-local. If the Container App scales to multiple
replicas, each replica holds its own cache — that is acceptable because ARG is
the source of truth and all replicas converge within one TTL window.

Never raises — on cache errors falls back to calling fetch_fn directly.
"""

import logging
import time
from threading import Lock
from typing import Any, Callable, Dict, FrozenSet, List, Tuple

logger = logging.getLogger(__name__)

# _cache maps (key, frozenset(subscription_ids)) → (timestamp, result)
_cache: Dict[Tuple[str, FrozenSet[str]], Tuple[float, Any]] = {}
_lock = Lock()


def get_cached(
    key: str,
    subscription_ids: List[str],
    ttl_seconds: int,
    fetch_fn: Callable[[], Any],
) -> Any:
    """Return cached result if fresh, otherwise call fetch_fn and cache the result.

    Args:
        key: Logical name for this dataset (e.g. "cert_expiry").
        subscription_ids: Subscription scope — part of the cache key so that
            different subscription sets never share results.
        ttl_seconds: How many seconds a cached result is considered fresh.
        fetch_fn: Zero-argument callable that returns the fresh result.

    Returns:
        The cached or freshly fetched result.
    """
    cache_key = (key, frozenset(subscription_ids))
    now = time.monotonic()

    with _lock:
        entry = _cache.get(cache_key)
        if entry is not None:
            cached_at, result = entry
            age = now - cached_at
            if age < ttl_seconds:
                logger.debug(
                    "arg_cache: HIT key=%s age=%.0fs ttl=%ds",
                    key,
                    age,
                    ttl_seconds,
                )
                return result

    # Cache miss or stale — fetch outside the lock to avoid blocking other threads
    logger.debug("arg_cache: MISS key=%s — fetching live", key)
    try:
        result = fetch_fn()
    except Exception as exc:
        logger.error("arg_cache: fetch_fn failed for key=%s: %s", key, exc)
        # Return stale data if available, else empty list
        with _lock:
            entry = _cache.get(cache_key)
        if entry is not None:
            logger.warning("arg_cache: returning stale data for key=%s", key)
            return entry[1]
        return []

    with _lock:
        _cache[cache_key] = (time.monotonic(), result)

    return result


def invalidate(key: str, subscription_ids: List[str] | None = None) -> None:
    """Remove one or all entries for a given key.

    Args:
        key: Cache key prefix to invalidate.
        subscription_ids: If provided, only invalidate the entry for this
            exact subscription set. If None, invalidate all entries for key.
    """
    with _lock:
        if subscription_ids is not None:
            _cache.pop((key, frozenset(subscription_ids)), None)
        else:
            to_delete = [k for k in _cache if k[0] == key]
            for k in to_delete:
                del _cache[k]
    logger.debug("arg_cache: invalidated key=%s", key)
