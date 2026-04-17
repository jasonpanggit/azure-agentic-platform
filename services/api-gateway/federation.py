from __future__ import annotations
"""Subscription federation helpers for inventory endpoints.

Provides resolve_subscription_ids() — the single source of truth for
determining which subscription IDs to query when an endpoint is called
with or without an explicit 'subscriptions' parameter.

Priority:
1. Explicit subscriptions= query param — caller-specified subset
2. app.state.subscription_registry.get_all_ids() — all discovered subscriptions
3. [] — empty fallback (triggers graceful no-op in ARG-backed endpoints)
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def resolve_subscription_ids(
    subscriptions_param: Optional[str],
    request: object,
) -> List[str]:
    """Resolve the effective subscription IDs for an ARG query.

    Args:
        subscriptions_param: Raw value of the ``subscriptions`` query parameter.
            ``None`` when the caller omits the param entirely.
        request: FastAPI ``Request`` object.  Used to read
            ``request.app.state.subscription_registry``.  May be ``None``
            in unit tests that do not construct a full request.

    Returns:
        List of subscription ID strings (may be empty).
    """
    # Priority 1 — explicit caller-specified subscriptions
    if subscriptions_param:
        ids = [s.strip() for s in subscriptions_param.split(",") if s.strip()]
        if ids:
            return ids

    # Priority 2 — registry-all from app.state
    app_state = getattr(getattr(request, "app", None), "state", None)
    if app_state is not None:
        registry = getattr(app_state, "subscription_registry", None)
        if registry is not None:
            try:
                ids = registry.get_all_ids()
                if ids:
                    logger.debug(
                        "federation: resolved %d subscriptions from registry", len(ids)
                    )
                return list(ids)
            except Exception as exc:  # pragma: no cover
                logger.warning("federation: registry.get_all_ids() failed | error=%s", exc)

    # Priority 3 — empty (caller must handle gracefully)
    return []
