"""Resource-scoped chat endpoint for VM investigation.

POST /api/v1/vms/{resource_id_base64}/chat
  Body: { message: str, thread_id: str | null, incident_id: str | null }

Creates or continues a Foundry thread routed directly to the compute agent
(not the orchestrator). On new thread creation, injects the incident's
pre-fetched evidence as system context so the agent's first response is
grounded in pre-fetched facts, not live tool calls.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.foundry import _get_foundry_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["vm-chat"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class VMChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    incident_id: Optional[str] = None
    user_id: Optional[str] = None


class VMChatResponse(BaseModel):
    thread_id: str
    run_id: str
    status: str = "created"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_resource_id(encoded: str) -> str:
    """Decode base64url-encoded ARM resource ID."""
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Invalid base64url resource ID: {exc}") from exc


def _load_evidence(cosmos_client: Any, incident_id: str) -> Optional[dict]:
    """Load pre-fetched evidence document from Cosmos evidence container."""
    try:
        db_name = os.environ.get("COSMOS_DATABASE", "aap")
        container = cosmos_client.get_database_client(db_name).get_container_client("evidence")
        item = container.read_item(item=incident_id, partition_key=incident_id)
        return item
    except Exception as exc:
        logger.debug("vm_chat: evidence not found | incident_id=%s error=%s", incident_id, exc)
        return None


def _load_latest_evidence_for_resource(cosmos_client: Any, resource_id: str) -> Optional[dict]:
    """Load the most recent evidence document for a resource across all incidents."""
    try:
        db_name = os.environ.get("COSMOS_DATABASE", "aap")

        # First find the most recent active incident for this resource
        inc_container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
        query = """
            SELECT TOP 1 c.incident_id FROM c
            WHERE c.resource_id = @resource_id
            AND c.investigation_status = 'evidence_ready'
            ORDER BY c.created_at DESC
        """
        items = list(inc_container.query_items(
            query=query,
            parameters=[{"name": "@resource_id", "value": resource_id}],
            enable_cross_partition_query=True,
        ))
        if not items:
            return None

        incident_id = items[0]["incident_id"]
        return _load_evidence(cosmos_client, incident_id)
    except Exception as exc:
        logger.debug("vm_chat: latest evidence lookup failed | resource=%s error=%s", resource_id[-60:], exc)
        return None


def _build_evidence_context(resource_id: str, evidence: Optional[dict]) -> str:
    """Build a system context string from pre-fetched evidence.

    This is injected as the first message on a new thread so the compute agent
    has immediate context without needing to call diagnostic tools first.
    """
    resource_name = resource_id.rstrip("/").split("/")[-1]

    if not evidence or not evidence.get("evidence_summary"):
        return (
            f"You are investigating Azure VM: {resource_name} ({resource_id}). "
            "No pre-fetched evidence is available yet. "
            "Use your diagnostic tools to gather activity log, resource health, and metrics data."
        )

    summary = evidence["evidence_summary"]
    health_state = summary.get("health_state", "Unknown")
    recent_changes = summary.get("recent_changes", [])
    metric_anomalies = summary.get("metric_anomalies", [])
    log_errors = summary.get("log_errors", {})
    collected_at = evidence.get("collected_at", "unknown time")

    lines = [
        f"## VM Investigation Context — {resource_name}",
        f"**Resource ID:** {resource_id}",
        f"**Evidence collected:** {collected_at}",
        "",
        f"### Health State: {health_state}",
    ]

    if recent_changes:
        lines.append("")
        lines.append(f"### Recent Activity (last 2h) — {len(recent_changes)} events")
        for change in recent_changes[:5]:
            ts = change.get("timestamp", "")[:19].replace("T", " ")
            op = change.get("operation", "")
            caller = change.get("caller", "")
            st = change.get("status", "")
            lines.append(f"- {ts}: {op} by {caller} — {st}")
        if len(recent_changes) > 5:
            lines.append(f"- ... and {len(recent_changes) - 5} more events")
    else:
        lines.append("")
        lines.append("### Recent Activity: No activity log events in last 2h")

    if metric_anomalies:
        lines.append("")
        lines.append(f"### Metric Anomalies ({len(metric_anomalies)} detected)")
        for anomaly in metric_anomalies:
            name = anomaly.get("metric_name", "")
            val = anomaly.get("current_value", 0)
            thresh = anomaly.get("threshold", 0)
            unit = anomaly.get("unit", "")
            lines.append(f"- {name}: {val:.1f}{unit} (threshold: {thresh}{unit})")

    if log_errors.get("count", 0) > 0:
        lines.append("")
        lines.append(f"### Log Errors: {log_errors['count']} errors detected")
        for sample in (log_errors.get("sample") or [])[:3]:
            lines.append(f"  - {sample}")

    lines.extend([
        "",
        "---",
        "Use this context to guide your investigation. Call diagnostic tools for additional detail.",
        "If you recommend any remediation actions, use propose_* tools — never execute directly.",
    ])

    return "\n".join(lines)


async def _create_or_continue_vm_thread(
    resource_id: str,
    request: VMChatRequest,
    cosmos_client: Any,
    user_id: str,
) -> dict[str, str]:
    """Create or continue a Foundry thread for VM investigation.

    New threads: inject evidence context as a system message before the user message.
    Continuing threads: just append the user message.
    """
    # Use orchestrator so connected_agent tools (compute, network, etc.) are available.
    # Direct compute agent runs have no tools — orchestrator routes to compute via connected_agent.
    compute_agent_id = (
        os.environ.get("ORCHESTRATOR_AGENT_ID")
        or os.environ.get("COMPUTE_AGENT_ID")
    )
    if not compute_agent_id:
        raise ValueError(
            "ORCHESTRATOR_AGENT_ID environment variable is required for resource-scoped chat."
        )

    client = _get_foundry_client()
    start = time.monotonic()

    thread_id = request.thread_id
    is_new_thread = not thread_id

    if thread_id:
        # Continue existing thread — cancel any active runs first
        logger.info("vm_chat: continuing thread %s | resource=%s", thread_id, resource_id[-60:])
        try:
            runs = list(client.runs.list(thread_id=thread_id))
            active = {"queued", "in_progress", "requires_action", "cancelling"}
            for run in runs:
                if run.status in active:
                    logger.info("vm_chat: cancelling run %s (status=%s)", run.id, run.status)
                    try:
                        client.runs.cancel(thread_id=thread_id, run_id=run.id)
                    except Exception as cancel_exc:
                        logger.warning("vm_chat: cancel run failed | %s", cancel_exc)
            if any(r.status in active for r in runs):
                await asyncio.sleep(1)
        except Exception as exc:
            logger.warning("vm_chat: list/cancel runs failed | thread=%s error=%s", thread_id, exc)
    else:
        # Create new thread
        thread = client.threads.create()
        thread_id = thread.id
        logger.info("vm_chat: created thread %s | resource=%s user=%s", thread_id, resource_id[-60:], user_id)

        # Inject evidence context as system message (before user message)
        if cosmos_client:
            evidence = None
            if request.incident_id:
                evidence = await asyncio.get_event_loop().run_in_executor(
                    None, _load_evidence, cosmos_client, request.incident_id
                )
            if not evidence:
                evidence = await asyncio.get_event_loop().run_in_executor(
                    None, _load_latest_evidence_for_resource, cosmos_client, resource_id
                )

            context = _build_evidence_context(resource_id, evidence)
            client.messages.create(
                thread_id=thread_id,
                role="user",
                content=context,
            )
            logger.info(
                "vm_chat: evidence context injected | thread=%s evidence=%s",
                thread_id,
                "found" if evidence else "none",
            )

    # Append the operator's actual message
    client.messages.create(
        thread_id=thread_id,
        role="user",
        content=request.message,
    )

    # Create run on compute agent directly (not orchestrator)
    run = client.runs.create(
        thread_id=thread_id,
        agent_id=compute_agent_id,
    )

    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "vm_chat: run created | thread=%s run=%s agent=compute new_thread=%s duration_ms=%.0f",
        thread_id, run.id, is_new_thread, duration_ms,
    )

    return {"thread_id": thread_id, "run_id": run.id}


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------

@router.post("/{resource_id_base64}/chat", response_model=VMChatResponse)
async def start_vm_chat(
    resource_id_base64: str,
    payload: VMChatRequest,
    credential=Depends(get_credential),
    cosmos_client=Depends(get_optional_cosmos_client),
    token: dict[str, Any] = Depends(verify_token),
) -> VMChatResponse:
    """Start or continue a resource-scoped compute agent conversation.

    On new threads, injects pre-fetched diagnostic evidence as context
    so the agent's first response is grounded without live tool calls.
    Subsequent messages in the same thread continue naturally.

    The thread/run IDs are returned so the frontend can poll
    GET /api/v1/chat/{thread_id}/result and SSE stream via /api/stream.
    """
    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = payload.user_id or token.get("sub", "unknown")
    logger.info(
        "vm_chat: request | resource=%s user=%s new_thread=%s",
        resource_id[-60:], user_id, not payload.thread_id,
    )

    try:
        result = await _create_or_continue_vm_thread(
            resource_id=resource_id,
            request=payload,
            cosmos_client=cosmos_client,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception as exc:
        logger.error("vm_chat: failed | resource=%s error=%s", resource_id[-60:], exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Foundry error: {exc}")

    return VMChatResponse(
        thread_id=result["thread_id"],
        run_id=result["run_id"],
        status="created" if not payload.thread_id else "continued",
    )
