"""IaC Drift Detection endpoints — list findings, trigger scans (Phase 58)."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.drift_detector import DriftDetector

router = APIRouter(prefix="/api/v1/drift", tags=["drift"])
logger = logging.getLogger(__name__)

# In-memory job tracker (lightweight; restarts clear history — acceptable for scan jobs)
_scan_jobs: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Background scan task
# ---------------------------------------------------------------------------


def _run_scan_job(
    job_id: str,
    detector: DriftDetector,
) -> None:
    """Execute drift scan and update job status in _scan_jobs. Non-fatal."""
    _scan_jobs[job_id]["status"] = "running"
    try:
        result = detector.run_scan(save_to_cosmos=True)
        _scan_jobs[job_id].update({
            "status": "completed",
            "result": {
                "total_findings": result.get("total_findings", 0),
                "scanned_resources": result.get("scanned_resources", 0),
                "scanned_at": result.get("scanned_at"),
                "duration_ms": result.get("duration_ms"),
            },
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "drift_scan: job=%s completed findings=%d",
            job_id, result.get("total_findings", 0),
        )
    except Exception as exc:
        _scan_jobs[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.warning("drift_scan: job=%s failed | error=%s", job_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/findings")
async def list_drift_findings(
    severity: Optional[str] = Query(None, description="Filter by severity: LOW, MEDIUM, HIGH, CRITICAL"),
    resource_type: Optional[str] = Query(None, description="Filter by Terraform resource type"),
    limit: int = Query(50, ge=1, le=200, description="Maximum findings to return"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return stored drift findings from Cosmos DB.

    Supports filtering by severity and resource_type.
    """
    start_time = time.monotonic()
    try:
        detector = DriftDetector(credential=credential, cosmos_client=cosmos_client)
        result = detector.list_findings(
            severity=severity,
            resource_type=resource_type,
            limit=limit,
        )
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "drift_findings: severity=%s resource_type=%s limit=%d findings=%d duration_ms=%s",
            severity, resource_type, limit, result.get("total", 0), duration_ms,
        )
        return result
    except Exception as exc:
        logger.warning("drift_findings: error | error=%s", exc)
        return JSONResponse({"error": str(exc), "findings": []}, status_code=500)


@router.post("/scan")
async def trigger_drift_scan(
    background_tasks: BackgroundTasks,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Trigger an immediate async drift scan.

    Returns a job_id to poll for status via GET /api/v1/drift/scan/{job_id}.
    """
    start_time = time.monotonic()
    job_id = f"drift-scan-{uuid.uuid4().hex[:8]}"
    _scan_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }

    detector = DriftDetector(credential=credential, cosmos_client=cosmos_client)
    background_tasks.add_task(_run_scan_job, job_id, detector)

    duration_ms = round((time.monotonic() - start_time) * 1000, 1)
    logger.info("drift_scan: job=%s queued duration_ms=%s", job_id, duration_ms)
    return {"job_id": job_id, "status": "queued", "queued_at": _scan_jobs[job_id]["queued_at"]}


@router.get("/scan/{job_id}")
async def get_scan_status(job_id: str) -> Any:
    """Poll the status of a drift scan job."""
    job = _scan_jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": f"Job {job_id!r} not found"}, status_code=404)
    return job


@router.get("/findings/{finding_id}/fix")
async def propose_fix(
    finding_id: str,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return a proposed Terraform HCL diff for a specific finding."""
    start_time = time.monotonic()
    try:
        detector = DriftDetector(credential=credential, cosmos_client=cosmos_client)
        # Look up finding from Cosmos
        result = detector.list_findings(limit=200)
        findings = result.get("findings", [])
        finding = next(
            (f for f in findings if f.get("finding_id") == finding_id or f.get("id") == finding_id),
            None,
        )
        if finding is None:
            return JSONResponse({"error": f"Finding {finding_id!r} not found"}, status_code=404)
        diff = detector.propose_terraform_fix(finding)
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info("drift_fix: finding_id=%s duration_ms=%s", finding_id, duration_ms)
        return {"finding_id": finding_id, "diff": diff, "duration_ms": duration_ms}
    except Exception as exc:
        logger.warning("drift_fix: error | finding_id=%s error=%s", finding_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
