from __future__ import annotations
"""Runbook automation endpoints — execute runbooks and manage automation steps."""

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.runbook_executor import (
    AVAILABLE_TOOLS,
    BUILTIN_RUNBOOKS,
    RunbookExecutor,
)

router = APIRouter(prefix="/api/v1/runbooks", tags=["runbooks-automation"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory store for custom automation steps (keyed by runbook_id)
# In production this would persist to PostgreSQL
# ---------------------------------------------------------------------------
_CUSTOM_AUTOMATION_STEPS: dict[str, list[dict]] = {}


def _get_executor(cosmos_client: Optional[Any] = None) -> RunbookExecutor:
    return RunbookExecutor(cosmos_client=cosmos_client)


# ---------------------------------------------------------------------------
# GET /api/v1/runbooks/tools
# ---------------------------------------------------------------------------


@router.get("/tools")
async def list_available_tools() -> JSONResponse:
    """Return the list of available tool names for the step builder."""
    return JSONResponse({"tools": AVAILABLE_TOOLS, "total": len(AVAILABLE_TOOLS)})


# ---------------------------------------------------------------------------
# PUT /api/v1/runbooks/{runbook_id}/automation-steps
# ---------------------------------------------------------------------------


@router.put("/{runbook_id}/automation-steps")
async def save_automation_steps(
    runbook_id: str,
    body: dict,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Save automation steps for a runbook.

    Persists steps to the in-memory store keyed by runbook_id.
    Body: { "automation_steps": [ {...}, ... ] }
    """
    try:
        steps = body.get("automation_steps", [])
        if not isinstance(steps, list):
            return JSONResponse(
                {"success": False, "error": "automation_steps must be a list"},
                status_code=422,
            )

        _CUSTOM_AUTOMATION_STEPS[runbook_id] = steps
        logger.info("Saved %d automation steps for runbook %s", len(steps), runbook_id)
        return JSONResponse(
            {
                "success": True,
                "runbook_id": runbook_id,
                "step_count": len(steps),
            }
        )
    except Exception as exc:
        logger.error("Failed to save automation steps for %s: %s", runbook_id, exc)
        return JSONResponse(
            {"success": False, "error": str(exc)},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# POST /api/v1/runbooks/{runbook_id}/execute
# ---------------------------------------------------------------------------


@router.post("/{runbook_id}/execute")
async def execute_runbook(
    runbook_id: str,
    body: dict,
    dry_run: bool = Query(default=False, description="Simulate execution without side effects"),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> StreamingResponse:
    """Execute a runbook against an incident context, streaming SSE step results.

    Body: { "incident_context": { "resource_id": "...", "subscription_id": "...", ... } }
    Streams: text/event-stream with JSON-encoded step events.
    """
    incident_context: dict = body.get("incident_context", {})

    # If runbook has custom steps saved, inject them into a copy of the builtin
    runbook_data = dict(BUILTIN_RUNBOOKS.get(runbook_id, {}))
    if runbook_id in _CUSTOM_AUTOMATION_STEPS:
        runbook_data["automation_steps"] = _CUSTOM_AUTOMATION_STEPS[runbook_id]
        # If runbook is not in BUILTIN_RUNBOOKS but has custom steps, create a minimal entry
        if not runbook_data:
            runbook_data = {
                "runbook_id": runbook_id,
                "name": runbook_id,
                "description": "Custom runbook",
                "domain": "ops",
                "automation_steps": _CUSTOM_AUTOMATION_STEPS[runbook_id],
            }
        # Temporarily patch BUILTIN_RUNBOOKS view for this request
        import services.api_gateway.runbook_executor as _rex_module
        _patched = {**_rex_module.BUILTIN_RUNBOOKS, runbook_id: runbook_data}
    else:
        import services.api_gateway.runbook_executor as _rex_module
        _patched = _rex_module.BUILTIN_RUNBOOKS

    executor = _get_executor(cosmos_client=cosmos_client)

    async def _stream():
        try:
            # Use patched BUILTIN_RUNBOOKS for this request
            original = _rex_module.BUILTIN_RUNBOOKS
            _rex_module.BUILTIN_RUNBOOKS = _patched
            try:
                async for event in executor.execute(
                    runbook_id=runbook_id,
                    incident_context=incident_context,
                    dry_run=dry_run,
                ):
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                _rex_module.BUILTIN_RUNBOOKS = original
        except Exception as exc:
            logger.error("Runbook execution stream error: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
