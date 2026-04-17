"""Runbook history endpoints — Phase 85.

Router prefix: /api/v1/runbooks/history, /api/v1/runbooks/stats,
               /api/v1/runbooks/incidents/{incident_id}
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.runbook_history_service import (
    get_execution_by_incident,
    get_execution_history,
    get_runbook_stats,
)

router = APIRouter(prefix="/api/v1/runbooks", tags=["runbook-history"])
logger = logging.getLogger(__name__)

COSMOS_DATABASE_NAME = os.environ.get("COSMOS_DATABASE_NAME", "aap")


def _serialise_execution(e: Any) -> Dict[str, Any]:
    d = asdict(e)
    return d


# ---------------------------------------------------------------------------
# GET /api/v1/runbooks/history
# ---------------------------------------------------------------------------


@router.get("/history")
async def list_runbook_history(
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    action_class: Optional[str] = Query(None, description="SAFE | CAUTIOUS | DESTRUCTIVE"),
    status: Optional[str] = Query(None, description="RESOLVED | IMPROVED | DEGRADED | TIMEOUT | BLOCKED"),
    limit: int = Query(100, ge=1, le=500),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return runbook execution history from remediation_audit container."""
    subscription_ids = [subscription_id] if subscription_id else None
    executions = get_execution_history(
        cosmos_client=cosmos_client,
        db_name=COSMOS_DATABASE_NAME,
        subscription_ids=subscription_ids,
        action_class=action_class,
        status=status,
        limit=limit,
    )
    return JSONResponse({
        "executions": [_serialise_execution(e) for e in executions],
        "total": len(executions),
    })


# ---------------------------------------------------------------------------
# GET /api/v1/runbooks/stats
# ---------------------------------------------------------------------------


@router.get("/stats")
async def get_history_stats(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return aggregated runbook execution statistics."""
    stats = get_runbook_stats(
        cosmos_client=cosmos_client,
        db_name=COSMOS_DATABASE_NAME,
        days=days,
    )
    result = {
        "total_executions": stats.total_executions,
        "success_rate": stats.success_rate,
        "avg_duration_ms": stats.avg_duration_ms,
        "by_action": stats.by_action,
        "by_status": stats.by_status,
        "by_action_class": stats.by_action_class,
        "top_resources": stats.top_resources,
        "recent_failures": [_serialise_execution(e) for e in stats.recent_failures],
    }
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# GET /api/v1/runbooks/incidents/{incident_id}
# ---------------------------------------------------------------------------


@router.get("/incidents/{incident_id}")
async def list_executions_for_incident(
    incident_id: str,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return all runbook executions for a specific incident."""
    executions = get_execution_by_incident(
        cosmos_client=cosmos_client,
        db_name=COSMOS_DATABASE_NAME,
        incident_id=incident_id,
    )
    return JSONResponse({
        "incident_id": incident_id,
        "executions": [_serialise_execution(e) for e in executions],
        "total": len(executions),
    })
