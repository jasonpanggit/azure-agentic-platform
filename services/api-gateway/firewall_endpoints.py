from __future__ import annotations
"""Azure Firewall API endpoints (Phase 104).

Routes:
  GET /api/v1/firewall/rules   — list firewalls + rules (live ARG, 900s TTL cache)
  GET /api/v1/firewall/audit   — classify rules into audit findings (live ARG, 900s TTL cache)

Data is queried live from Azure Resource Graph on every request (within TTL window).
No scan button, no Cosmos intermediary.
"""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from services.api_gateway.arg_cache import get_cached
from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.firewall_service import get_firewall_audit, get_firewall_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/firewall", tags=["firewall"])

_CACHE_TTL = 900  # 15 minutes — resource inventory volatility


@router.get("/rules")
async def list_firewall_rules(
    request: Request,
    subscription_ids: Optional[str] = Query(
        None, description="Comma-separated subscription IDs to query"
    ),
    _token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return Azure Firewall resources and their policy rules queried live from ARG (900s TTL cache)."""
    start_time = time.monotonic()

    sub_ids = resolve_subscription_ids(subscription_ids, request)

    result = get_cached(
        key="firewall_rules",
        subscription_ids=sub_ids,
        ttl_seconds=_CACHE_TTL,
        fetch_fn=lambda: get_firewall_rules(sub_ids, credential=credential),
    )

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /firewall/rules → %d rules, %d firewalls (%.0fms)",
        result.get("count", 0), len(result.get("firewalls", [])), duration_ms,
    )
    return result


@router.get("/audit")
async def firewall_audit(
    request: Request,
    subscription_ids: Optional[str] = Query(
        None, description="Comma-separated subscription IDs to query"
    ),
    severity: Optional[str] = Query(
        None, description="Filter by severity: critical | high | medium"
    ),
    _token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return firewall audit findings classified from ARG data (900s TTL cache).

    Query params:
    - subscription_ids: comma-separated subscription IDs
    - severity: one of critical, high, medium (optional filter)
    """
    start_time = time.monotonic()

    valid_severities = {"critical", "high", "medium"}
    if severity and severity.lower() not in valid_severities:
        return JSONResponse(
            status_code=422,
            content={"error": f"severity must be one of: {sorted(valid_severities)}"},
        )

    sub_ids = resolve_subscription_ids(subscription_ids, request)
    norm_severity = severity.lower() if severity else None

    # Cache key includes severity so filtered results are cached independently
    cache_key = f"firewall_audit_{norm_severity or 'all'}"

    result = get_cached(
        key=cache_key,
        subscription_ids=sub_ids,
        ttl_seconds=_CACHE_TTL,
        fetch_fn=lambda: get_firewall_audit(
            sub_ids, credential=credential, severity_filter=norm_severity
        ),
    )

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /firewall/audit → %d findings severity=%s (%.0fms)",
        result.get("summary", {}).get("total", 0), severity, duration_ms,
    )
    return result
