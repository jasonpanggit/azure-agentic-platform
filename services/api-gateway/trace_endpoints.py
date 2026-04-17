"""Trace endpoints — GET /api/v1/traces and GET /api/v1/traces/{thread_id}/{run_id}."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.trace_service import get_trace_by_id, get_traces

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/traces")
async def list_traces(
    thread_id: Optional[str] = Query(None, description="Filter by thread ID"),
    incident_id: Optional[str] = Query(None, description="Filter by incident ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cosmos_client=Depends(get_optional_cosmos_client),
):
    """List agent run traces with optional filtering."""
    traces, total = await get_traces(
        cosmos_client,
        "aap",
        thread_id=thread_id,
        incident_id=incident_id,
        limit=limit,
        offset=offset,
    )
    return {
        "traces": traces,
        "total": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/v1/traces/{thread_id}/{run_id}")
async def get_trace(
    thread_id: str,
    run_id: str,
    cosmos_client=Depends(get_optional_cosmos_client),
):
    """Get full trace details including all steps and tool calls."""
    trace = await get_trace_by_id(cosmos_client, "aap", thread_id, run_id)
    if trace is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Trace {thread_id}/{run_id} not found")
    return trace
