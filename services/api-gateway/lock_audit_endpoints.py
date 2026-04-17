"""FastAPI router for resource lock audit endpoints.

Prefix: /api/v1/locks

Endpoints:
- GET  /api/v1/locks/findings           — filtered findings list
- GET  /api/v1/locks/summary            — aggregate stats
- GET  /api/v1/locks/remediation-script — az CLI script (text/plain)
- POST /api/v1/locks/scan               — trigger background scan
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import PlainTextResponse

from services.api_gateway.dependencies import get_cosmos_client, get_credential
from services.api_gateway.lock_audit_service import (
    generate_lock_remediation_script,
    get_lock_findings,
    get_lock_summary,
    persist_lock_findings,
    scan_lock_compliance,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/locks", tags=["lock-audit"])

# ──────────────────────────────────────────────────────────────────────────────
# Helper — subscription list from env (same pattern as other endpoints)
# ──────────────────────────────────────────────────────────────────────────────

import os


def _default_subscription_ids() -> List[str]:
    raw = os.environ.get("AZURE_SUBSCRIPTION_IDS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


COSMOS_DB_NAME = os.environ.get("COSMOS_DB_NAME", "aap-db")


# ──────────────────────────────────────────────────────────────────────────────
# Background scan worker
# ──────────────────────────────────────────────────────────────────────────────


def _run_scan_background(
    credential: Any,
    cosmos_client: Any,
    subscription_ids: List[str],
) -> None:
    findings = scan_lock_compliance(credential, subscription_ids)
    if findings:
        persist_lock_findings(cosmos_client, COSMOS_DB_NAME, findings)
    logger.info("lock_audit: background scan done | findings=%d", len(findings))


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/findings")
def get_findings(
    subscription_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Return lock findings, optionally filtered."""
    sub_ids = [subscription_id] if subscription_id else None
    findings = get_lock_findings(
        cosmos_client,
        COSMOS_DB_NAME,
        subscription_ids=sub_ids,
        severity=severity,
        resource_type=resource_type,
    )
    return {
        "findings": [
            {
                "finding_id": f.finding_id,
                "resource_id": f.resource_id,
                "resource_name": f.resource_name,
                "resource_type": f.resource_type,
                "resource_group": f.resource_group,
                "subscription_id": f.subscription_id,
                "location": f.location,
                "lock_status": f.lock_status,
                "severity": f.severity,
                "recommendation": f.recommendation,
                "scanned_at": f.scanned_at,
            }
            for f in findings
        ],
        "total": len(findings),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/summary")
def get_summary(
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Return aggregate lock audit statistics."""
    summary = get_lock_summary(cosmos_client, COSMOS_DB_NAME)
    return summary


@router.get("/remediation-script", response_class=PlainTextResponse)
def get_remediation_script(
    subscription_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> str:
    """Return an az CLI script to remediate lock findings."""
    sub_ids = [subscription_id] if subscription_id else None
    findings = get_lock_findings(
        cosmos_client,
        COSMOS_DB_NAME,
        subscription_ids=sub_ids,
        severity=severity,
    )
    return generate_lock_remediation_script(findings)


@router.post("/scan")
def trigger_scan(
    background_tasks: BackgroundTasks,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> Any:
    """Queue a lock compliance scan in the background."""
    scan_id = str(uuid.uuid4())
    subscription_ids = _default_subscription_ids()
    background_tasks.add_task(
        _run_scan_background,
        credential,
        cosmos_client,
        subscription_ids,
    )
    logger.info("lock_audit: scan queued | scan_id=%s subscriptions=%d", scan_id, len(subscription_ids))
    return {
        "scan_id": scan_id,
        "status": "queued",
        "subscription_count": len(subscription_ids),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
