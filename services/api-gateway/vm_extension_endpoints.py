from __future__ import annotations
"""VM Extension Health Audit endpoints (Phase 89).

Routes:
  GET  /api/v1/vm-extensions          — list findings (filter by subscription_id, severity)
  GET  /api/v1/vm-extensions/summary  — aggregate compliance summary
  POST /api/v1/vm-extensions/scan     — trigger a live scan
"""
import os
import os

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_cosmos_client, get_credential
from services.api_gateway.vm_extension_service import (
    get_extension_summary,
    get_findings,
    persist_findings,
    scan_vm_extensions,
)

router = APIRouter(prefix="/api/v1/vm-extensions", tags=["vm-extensions"])
logger = logging.getLogger(__name__)

_DB_NAME = os.environ.get("COSMOS_OPS_DB_NAME", "aap-ops")


@router.get("")
async def list_vm_extension_findings(
    subscription_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return VM extension findings, optionally filtered."""
    subs = [subscription_id] if subscription_id else None
    findings = get_findings(cosmos_client, _DB_NAME, subscription_ids=subs, severity=severity)
    return JSONResponse({"findings": findings, "total": len(findings)})


@router.get("/summary")
async def vm_extension_summary(
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Return aggregate extension compliance summary."""
    summary = get_extension_summary(cosmos_client, _DB_NAME)
    return JSONResponse(summary)


@router.post("/scan")
async def trigger_vm_extension_scan(
    subscription_id: Optional[str] = Query(None),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_cosmos_client),
) -> JSONResponse:
    """Trigger a live VM extension scan and persist results."""
    try:
        from services.api_gateway.subscription_registry import SubscriptionRegistry
        registry = SubscriptionRegistry()
        all_subs = await registry.list_subscription_ids()
    except Exception:  # noqa: BLE001
        all_subs = [subscription_id] if subscription_id else []

    if subscription_id:
        all_subs = [subscription_id]

    findings = scan_vm_extensions(credential, all_subs)
    persist_findings(cosmos_client, _DB_NAME, findings)

    logger.info("vm_extension_endpoints: scan complete | findings=%d", len(findings))
    return JSONResponse({
        "status": "ok",
        "findings_count": len(findings),
        "subscriptions_scanned": len(all_subs),
    })
