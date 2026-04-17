"""Azure Policy Compliance Drill-Down endpoints (Phase 84).

Router prefix: /api/v1/policy

GET  /api/v1/policy/violations  — list violations (filter: subscription_id, severity, policy_name)
GET  /api/v1/policy/summary     — aggregate summary
POST /api/v1/policy/scan        — trigger background scan
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/policy", tags=["policy-compliance"])


def _run_scan_background(credential: Any, subscription_ids: List[str], cosmos_client: Any) -> None:
    """Background task: scan and persist policy violations."""
    import os
    from services.api_gateway.policy_compliance_service import persist_violations, scan_policy_compliance

    db_name = os.environ.get("COSMOS_DATABASE", "aap")
    try:
        violations = scan_policy_compliance(credential, subscription_ids)
        if cosmos_client is not None:
            persist_violations(cosmos_client, db_name, violations)
        logger.info("policy_compliance_endpoints.scan_background: scanned=%d", len(violations))
    except Exception as exc:  # noqa: BLE001
        logger.error("policy_compliance_endpoints.scan_background: error=%s", exc)


@router.get("/violations")
async def list_policy_violations(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: high/medium/low"),
    policy_name: Optional[str] = Query(None, description="Free-text filter on policy display name"),
    _token: str = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Return non-compliant policy violation records from Cosmos DB."""
    import os
    from services.api_gateway.policy_compliance_service import get_violations

    start_time = time.monotonic()
    db_name = os.environ.get("COSMOS_DATABASE", "aap")

    subscription_ids = [subscription_id] if subscription_id else None
    violations = get_violations(cosmos_client, db_name, subscription_ids, severity, policy_name)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "policy_compliance_endpoints.violations: total=%d duration_ms=%.1f",
        len(violations), duration_ms,
    )
    return {"violations": violations, "total": len(violations)}


@router.get("/summary")
async def get_policy_compliance_summary(
    _token: str = Depends(verify_token),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregate policy compliance summary from Cosmos DB."""
    import os
    from services.api_gateway.policy_compliance_service import get_policy_summary

    db_name = os.environ.get("COSMOS_DATABASE", "aap")
    return get_policy_summary(cosmos_client, db_name)


@router.post("/scan")
async def trigger_policy_compliance_scan(
    background_tasks: BackgroundTasks,
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a background policy compliance scan across all registered subscriptions."""
    from services.api_gateway.subscription_registry import SubscriptionRegistry

    subscription_ids = SubscriptionRegistry.list_subscription_ids()
    if not subscription_ids:
        return {"status": "no_subscriptions", "message": "No subscriptions registered"}

    background_tasks.add_task(_run_scan_background, credential, subscription_ids, cosmos_client)
    logger.info(
        "policy_compliance_endpoints.scan: triggered for %d subscriptions",
        len(subscription_ids),
    )
    return {"status": "scanning", "subscription_count": len(subscription_ids)}
