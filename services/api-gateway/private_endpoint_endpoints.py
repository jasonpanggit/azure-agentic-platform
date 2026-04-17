"""Private Endpoint Compliance API endpoints (Phase 92).

Router prefix: /api/v1/private-endpoints
  GET  /api/v1/private-endpoints/findings  — filtered findings list
  GET  /api/v1/private-endpoints/summary   — aggregate summary
  POST /api/v1/private-endpoints/scan      — trigger background scan
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

router = APIRouter(prefix="/api/v1/private-endpoints", tags=["private-endpoints"])
logger = logging.getLogger(__name__)

_scan_jobs: Dict[str, Dict[str, Any]] = {}

COSMOS_DATABASE = "aap"


# ---------------------------------------------------------------------------
# Background scan helper
# ---------------------------------------------------------------------------

def _run_scan_job(
    job_id: str,
    credential: Any,
    subscription_ids: List[str],
    cosmos_client: Optional[Any],
) -> None:
    """Execute PE compliance scan and persist results. Non-fatal."""
    _scan_jobs[job_id]["status"] = "running"
    start_time = time.monotonic()
    try:
        from services.api_gateway.private_endpoint_service import (
            scan_private_endpoint_compliance,
            persist_findings,
        )
        findings = scan_private_endpoint_compliance(credential, subscription_ids)
        if cosmos_client is not None:
            persist_findings(cosmos_client, COSMOS_DATABASE, findings)

        duration_ms = (time.monotonic() - start_time) * 1000
        _scan_jobs[job_id].update({
            "status": "completed",
            "result": {
                "total_resources": len(findings),
                "high": sum(1 for f in findings if f.severity == "high"),
                "medium": sum(1 for f in findings if f.severity == "medium"),
                "duration_ms": round(duration_ms),
            },
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("pe_scan: job=%s completed resources=%d", job_id, len(findings))
    except Exception as exc:  # noqa: BLE001
        _scan_jobs[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.warning("pe_scan: job=%s failed | error=%s", job_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/findings")
async def get_pe_findings(
    subscription_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    credential: Any = Depends(get_credential),
    cosmos_client: Optional[Any] = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return PE compliance findings.

    Query params:
        subscription_id: Filter by subscription.
        severity: Filter by severity (high | medium | info).
        resource_type: Filter by friendly resource type label.
    """
    start_time = time.monotonic()

    if cosmos_client is None:
        logger.warning("pe/findings: Cosmos not configured — running live scan")
        from services.api_gateway.private_endpoint_service import scan_private_endpoint_compliance
        sub_ids = [subscription_id] if subscription_id else []
        findings = scan_private_endpoint_compliance(credential, sub_ids)
        if severity:
            findings = [f for f in findings if f.severity == severity]
        if resource_type:
            findings = [f for f in findings if f.resource_type == resource_type]
    else:
        from services.api_gateway.private_endpoint_service import get_findings
        sub_ids_list = [subscription_id] if subscription_id else None
        findings = get_findings(cosmos_client, COSMOS_DATABASE, sub_ids_list, severity, resource_type)

    from dataclasses import asdict as _asdict
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /private-endpoints/findings → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": [_asdict(f) for f in findings], "total": len(findings)}


@router.get("/summary")
async def get_pe_summary_endpoint(
    cosmos_client: Optional[Any] = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregate PE compliance summary."""
    start_time = time.monotonic()

    if cosmos_client is None:
        summary: Dict[str, Any] = {
            "total_resources": 0, "high_count": 0, "medium_count": 0,
            "info_count": 0, "pe_coverage_pct": 0.0, "by_resource_type": {},
        }
    else:
        from services.api_gateway.private_endpoint_service import get_pe_summary
        summary = get_pe_summary(cosmos_client, COSMOS_DATABASE)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /private-endpoints/summary → coverage=%.1f%% (%.0fms)", summary.get("pe_coverage_pct", 0), duration_ms)
    return summary


@router.post("/scan")
async def trigger_pe_scan(
    background_tasks: BackgroundTasks,
    subscription_id: Optional[str] = Query(default=None),
    credential: Any = Depends(get_credential),
    cosmos_client: Optional[Any] = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger an async PE compliance scan."""
    sub_ids: List[str] = []
    if subscription_id:
        sub_ids = [subscription_id]
    else:
        try:
            env_subs = os.environ.get("SUBSCRIPTION_IDS", "")
            sub_ids = [s.strip() for s in env_subs.split(",") if s.strip()]
        except Exception:  # noqa: BLE001
            sub_ids = []

    job_id = str(uuid.uuid4())
    _scan_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "subscription_ids": sub_ids,
    }

    background_tasks.add_task(
        _run_scan_job,
        job_id=job_id,
        credential=credential,
        subscription_ids=sub_ids,
        cosmos_client=cosmos_client,
    )

    logger.info("pe_scan: job=%s queued subs=%d", job_id, len(sub_ids))
    return {"job_id": job_id, "status": "queued", "subscription_ids": sub_ids}
