from __future__ import annotations
"""Storage Account Security API endpoints — Phase 98.

Routes:
  GET  /api/v1/storage/security?subscription_id=&severity=
  POST /api/v1/storage/security/scan
  GET  /api/v1/storage/security/summary?subscription_id=
"""
import os
import os

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/storage", tags=["storage-security"])

_COSMOS_DB = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


@router.get("/security")
async def list_storage_findings(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical|high|medium|low"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return storage account security findings from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.storage_security_service import get_storage_findings

    findings = (
        get_storage_findings(
            cosmos_client,
            _COSMOS_DB,
            subscription_id=subscription_id,
            severity=severity,
        )
        if cosmos_client
        else []
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /storage/security → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.post("/security/scan")
async def scan_storage(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live ARG scan for storage security misconfigurations and persist results."""
    start_time = time.monotonic()
    from services.api_gateway.storage_security_service import scan_storage_security, persist_storage_findings
    from services.api_gateway.subscription_registry import get_managed_subscription_ids

    subscription_ids: List[str] = []
    try:
        subscription_ids = await get_managed_subscription_ids()
    except Exception as exc:
        logger.warning("storage_security_endpoints: could not fetch subscription list: %s", exc)

    findings = scan_storage_security(credential, subscription_ids)
    if cosmos_client and findings:
        persist_storage_findings(cosmos_client, _COSMOS_DB, findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("POST /storage/security/scan → %d findings (%.0fms)", len(findings), duration_ms)
    return {
        "scanned": True,
        "findings_found": len(findings),
        "duration_ms": round(duration_ms),
    }


@router.get("/security/summary")
async def storage_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated storage security summary."""
    start_time = time.monotonic()
    from services.api_gateway.storage_security_service import get_storage_summary

    summary = (
        get_storage_summary(cosmos_client, _COSMOS_DB, subscription_id=subscription_id)
        if cosmos_client
        else {
            "total_accounts": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "top_risks": [],
        }
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /storage/security/summary (%.0fms)", duration_ms)
    return summary
