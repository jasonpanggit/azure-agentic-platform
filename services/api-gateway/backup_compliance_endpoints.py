"""Backup Compliance API endpoints (Phase 91).

Router prefix: /api/v1/backup
  GET  /api/v1/backup/findings  — filtered findings list
  GET  /api/v1/backup/summary   — aggregate summary
  POST /api/v1/backup/scan      — trigger background scan
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

router = APIRouter(prefix="/api/v1/backup", tags=["backup-compliance"])
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
    """Execute backup compliance scan and persist results. Non-fatal."""
    _scan_jobs[job_id]["status"] = "running"
    start_time = time.monotonic()
    try:
        from services.api_gateway.backup_compliance_service import (
            scan_backup_compliance,
            persist_findings,
        )
        findings = scan_backup_compliance(credential, subscription_ids)
        if cosmos_client is not None:
            persist_findings(cosmos_client, COSMOS_DATABASE, findings)

        duration_ms = (time.monotonic() - start_time) * 1000
        _scan_jobs[job_id].update({
            "status": "completed",
            "result": {
                "total_vms": len(findings),
                "unprotected": sum(1 for f in findings if f.backup_status == "unprotected"),
                "unhealthy": sum(1 for f in findings if f.backup_status == "unhealthy"),
                "duration_ms": round(duration_ms),
            },
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("backup_scan: job=%s completed vms=%d", job_id, len(findings))
    except Exception as exc:  # noqa: BLE001
        _scan_jobs[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.warning("backup_scan: job=%s failed | error=%s", job_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/findings")
async def get_backup_findings(
    subscription_id: Optional[str] = Query(default=None),
    backup_status: Optional[str] = Query(default=None),
    credential: Any = Depends(get_credential),
    cosmos_client: Optional[Any] = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return backup compliance findings from Cosmos DB.

    Query params:
        subscription_id: Filter by single subscription.
        backup_status: Filter by status (protected | unprotected | unhealthy).
    """
    start_time = time.monotonic()

    if cosmos_client is None:
        logger.warning("backup/findings: Cosmos not configured — running live scan")
        from services.api_gateway.backup_compliance_service import scan_backup_compliance
        sub_ids = [subscription_id] if subscription_id else []
        findings = scan_backup_compliance(credential, sub_ids)
        if backup_status:
            findings = [f for f in findings if f.backup_status == backup_status]
    else:
        from services.api_gateway.backup_compliance_service import get_findings
        from dataclasses import asdict
        sub_ids = [subscription_id] if subscription_id else None
        findings = get_findings(cosmos_client, COSMOS_DATABASE, sub_ids, backup_status)

    from dataclasses import asdict as _asdict
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /backup/findings → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": [_asdict(f) for f in findings], "total": len(findings)}


@router.get("/summary")
async def get_backup_summary_endpoint(
    cosmos_client: Optional[Any] = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregate backup compliance summary."""
    start_time = time.monotonic()

    if cosmos_client is None:
        summary: Dict[str, Any] = {
            "total_vms": 0, "protected": 0, "unprotected": 0,
            "unhealthy": 0, "protection_rate": 0.0, "recent_failures": 0,
        }
    else:
        from services.api_gateway.backup_compliance_service import get_backup_summary
        summary = get_backup_summary(cosmos_client, COSMOS_DATABASE)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /backup/summary → protection_rate=%.1f%% (%.0fms)", summary.get("protection_rate", 0), duration_ms)
    return summary


@router.post("/scan")
async def trigger_backup_scan(
    background_tasks: BackgroundTasks,
    subscription_id: Optional[str] = Query(default=None),
    credential: Any = Depends(get_credential),
    cosmos_client: Optional[Any] = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger an async backup compliance scan.

    Returns a job_id that can be used to poll for completion (via summary/findings).
    """
    sub_ids: List[str] = []
    if subscription_id:
        sub_ids = [subscription_id]
    else:
        try:
            registry = getattr(credential, "_registry", None)
            # Attempt to get IDs from app subscription registry via request scope
            import os
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

    logger.info("backup_scan: job=%s queued subs=%d", job_id, len(sub_ids))
    return {"job_id": job_id, "status": "queued", "subscription_ids": sub_ids}
