from __future__ import annotations
"""TLS / Certificate Expiry API endpoints — Phase 97.

Routes:
  GET  /api/v1/certs/expiry?subscription_id=&severity=&cert_type=
  POST /api/v1/certs/scan
  GET  /api/v1/certs/summary?subscription_id=
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

router = APIRouter(prefix="/api/v1/certs", tags=["cert-expiry"])

_COSMOS_DB = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


@router.get("/expiry")
async def list_cert_expiry(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical|high|medium|low"),
    cert_type: Optional[str] = Query(None, description="Filter by type: keyvault|app_service"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return certificate expiry findings from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.cert_expiry_service import get_cert_findings

    findings = (
        get_cert_findings(
            cosmos_client,
            _COSMOS_DB,
            subscription_id=subscription_id,
            severity=severity,
            cert_type=cert_type,
        )
        if cosmos_client
        else []
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /certs/expiry → %d findings (%.0fms)", len(findings), duration_ms)
    return {"findings": findings, "total": len(findings)}


@router.post("/scan")
async def scan_certs(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live ARG scan for expiring certificates and persist results."""
    start_time = time.monotonic()
    from services.api_gateway.cert_expiry_service import scan_cert_expiry, persist_cert_findings
    from services.api_gateway.subscription_registry import get_managed_subscription_ids

    subscription_ids: List[str] = []
    try:
        subscription_ids = await get_managed_subscription_ids()
    except Exception as exc:
        logger.warning("cert_expiry_endpoints: could not fetch subscription list: %s", exc)

    findings = scan_cert_expiry(credential, subscription_ids)
    if cosmos_client and findings:
        persist_cert_findings(cosmos_client, _COSMOS_DB, findings)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("POST /certs/scan → %d findings (%.0fms)", len(findings), duration_ms)
    return {
        "scanned": True,
        "findings_found": len(findings),
        "duration_ms": round(duration_ms),
    }


@router.get("/summary")
async def cert_summary(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated certificate expiry summary."""
    start_time = time.monotonic()
    from services.api_gateway.cert_expiry_service import get_cert_summary

    summary = (
        get_cert_summary(cosmos_client, _COSMOS_DB, subscription_id=subscription_id)
        if cosmos_client
        else {
            "total": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "soonest_expiry": None,
            "soonest_expiry_days": None,
        }
    )
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /certs/summary (%.0fms)", duration_ms)
    return summary
