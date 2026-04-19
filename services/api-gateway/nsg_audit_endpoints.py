from __future__ import annotations
"""NSG security audit API endpoints (Phase 77).

Provides:
  GET  /api/v1/nsg/findings         — list findings queried live from ARG (15m TTL cache)
  GET  /api/v1/nsg/findings/summary — severity counts + top risky NSGs (live ARG)
"""
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.arg_cache import get_cached
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.nsg_audit_service import scan_nsg_compliance

router = APIRouter(prefix="/api/v1/nsg", tags=["nsg-audit"])
logger = logging.getLogger(__name__)

_NSG_CACHE_TTL = 900  # 15 minutes — resource inventory volatility


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_subscription_ids() -> List[str]:
    """Read subscription IDs from SUBSCRIPTION_IDS env var."""
    raw = os.environ.get("SUBSCRIPTION_IDS", "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/findings")
async def list_nsg_findings(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical | high | medium | info"),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return NSG security findings queried live from ARG (15m TTL cache).

    Query params:
    - subscription_id: restrict to a single subscription
    - severity: one of critical, high, medium, info
    """
    valid_severities = {"critical", "high", "medium", "info"}
    if severity and severity.lower() not in valid_severities:
        return JSONResponse(
            status_code=422,
            content={"error": f"severity must be one of: {sorted(valid_severities)}"},
        )

    subscription_ids = _get_subscription_ids()

    findings = get_cached(
        key="nsg_findings",
        subscription_ids=subscription_ids,
        ttl_seconds=_NSG_CACHE_TTL,
        fetch_fn=lambda: scan_nsg_compliance(credential, subscription_ids),
    )

    # Apply optional filters
    if subscription_id:
        findings = [f for f in findings if f.subscription_id == subscription_id]
    if severity:
        sev_lower = severity.lower()
        findings = [f for f in findings if f.severity == sev_lower]

    return {
        "findings": [f.to_dict() for f in findings],
        "count": len(findings),
    }


@router.get("/findings/summary")
async def nsg_findings_summary(
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return aggregated NSG finding counts by severity and top 5 risky NSGs (live ARG, 15m TTL)."""
    subscription_ids = _get_subscription_ids()

    findings = get_cached(
        key="nsg_findings",
        subscription_ids=subscription_ids,
        ttl_seconds=_NSG_CACHE_TTL,
        fetch_fn=lambda: scan_nsg_compliance(credential, subscription_ids),
    )

    counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "info": 0, "total": 0}
    nsg_risk: Dict[str, int] = {}

    for f in findings:
        sev = f.severity
        if sev in counts:
            counts[sev] += 1
        counts["total"] += 1
        nsg_risk[f.nsg_name] = nsg_risk.get(f.nsg_name, 0) + 1

    top_risky = sorted(nsg_risk.items(), key=lambda x: x[1], reverse=True)[:5]

    from datetime import datetime, timezone  # noqa: PLC0415
    return {
        "counts": counts,
        "top_risky_nsgs": [{"nsg_name": name, "finding_count": cnt} for name, cnt in top_risky],
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
