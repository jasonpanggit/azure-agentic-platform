from __future__ import annotations
"""Private Endpoint Compliance API endpoints.

Router prefix: /api/v1/private-endpoints
  GET  /api/v1/private-endpoints/findings  — filtered findings (live ARG query)
  GET  /api/v1/private-endpoints/summary   — aggregate summary (live ARG query)

Data is queried live from Azure Resource Graph on every request.
"""

import logging
import time
from dataclasses import asdict as _asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.dependencies import get_credential
from services.api_gateway.federation import resolve_subscription_ids

router = APIRouter(prefix="/api/v1/private-endpoints", tags=["private-endpoints"])
logger = logging.getLogger(__name__)


@router.get("/findings")
async def get_pe_findings(
    request: Request,
    subscription_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return PE compliance findings queried live from ARG.

    Query params:
        subscription_id: Filter by subscription.
        severity: Filter by severity (high | medium | info).
        resource_type: Filter by friendly resource type label.
    """
    start_time = time.monotonic()
    from services.api_gateway.private_endpoint_service import scan_private_endpoint_compliance

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings = scan_private_endpoint_compliance(credential, subscription_ids)

    if severity:
        findings = [f for f in findings if f.severity == severity]
    if resource_type:
        findings = [f for f in findings if f.resource_type == resource_type]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /private-endpoints/findings → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": [_asdict(f) for f in findings], "total": len(findings)}


@router.get("/summary")
async def get_pe_summary_endpoint(
    request: Request,
    subscription_id: Optional[str] = Query(default=None),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return aggregate PE compliance summary queried live from ARG."""
    start_time = time.monotonic()
    from services.api_gateway.private_endpoint_service import scan_private_endpoint_compliance

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    findings = scan_private_endpoint_compliance(credential, subscription_ids)

    total = len(findings)
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    info = sum(1 for f in findings if f.severity == "info")
    compliant = sum(1 for f in findings if f.severity == "info")
    pe_coverage = round(compliant / total * 100, 1) if total > 0 else 0.0

    by_type: Dict[str, Dict[str, int]] = {}
    for f in findings:
        rt = f.resource_type
        entry = by_type.setdefault(rt, {"total": 0, "high": 0, "medium": 0, "info": 0})
        entry["total"] += 1
        entry[f.severity] = entry.get(f.severity, 0) + 1

    summary: Dict[str, Any] = {
        "total_resources": total,
        "high_count": high,
        "medium_count": medium,
        "info_count": info,
        "pe_coverage_pct": pe_coverage,
        "by_resource_type": by_type,
    }
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /private-endpoints/summary → coverage=%.1f%% (%.0fms)", pe_coverage, duration_ms)
    return summary
