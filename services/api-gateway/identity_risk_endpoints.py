"""Identity Risk API endpoints — Phase 93.

Routes:
  GET  /api/v1/identity-risks         — list risks (optional ?severity=)
  GET  /api/v1/identity-risks/summary — summary counts
  POST /api/v1/identity-risks/scan    — trigger live Graph scan
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_cosmos_client, get_credential, get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/identity-risks", tags=["identity-risks"])

_COSMOS_DB = "aap"


@router.get("")
async def list_identity_risks(
    severity: Optional[str] = Query(None, description="Filter by severity: critical|high|medium"),
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return service principal credential risks from the last scan."""
    start_time = time.monotonic()
    from services.api_gateway.identity_risk_service import get_risks
    risks = get_risks(cosmos_client, _COSMOS_DB, severity=severity) if cosmos_client else []
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /identity-risks → %d risks (%.0fms)", len(risks), duration_ms)
    return {"risks": [asdict(r) for r in risks], "total": len(risks)}


@router.get("/summary")
async def identity_risks_summary(
    token: Dict[str, Any] = Depends(verify_token),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Return aggregated identity risk summary."""
    start_time = time.monotonic()
    from services.api_gateway.identity_risk_service import get_identity_summary
    summary = get_identity_summary(cosmos_client, _COSMOS_DB) if cosmos_client else {
        "total_sps_checked": 0, "critical_count": 0, "high_count": 0,
        "medium_count": 0, "expired_count": 0, "expiring_30d_count": 0,
    }
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /identity-risks/summary (%.0fms)", duration_ms)
    return summary


@router.post("/scan")
async def scan_identity_risks(
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Dict[str, Any]:
    """Trigger a live Microsoft Graph scan and persist results."""
    start_time = time.monotonic()
    from services.api_gateway.identity_risk_service import scan_credential_risks, persist_risks

    risks = scan_credential_risks(credential)
    if cosmos_client and risks:
        persist_risks(cosmos_client, _COSMOS_DB, risks)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("POST /identity-risks/scan → %d risks (%.0fms)", len(risks), duration_ms)
    return {"scanned": True, "risks_found": len(risks), "duration_ms": round(duration_ms)}
