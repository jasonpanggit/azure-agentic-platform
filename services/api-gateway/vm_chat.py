from __future__ import annotations
"""Resource-scoped chat endpoint for VM investigation.

POST /api/v1/vms/{resource_id_base64}/chat
  Body: { message: str, thread_id: str | null, incident_id: str | null }

Uses chat.completions with function calling so the LLM can invoke live Azure
SDK tools (get_vm_metrics, get_activity_logs, get_resource_health,
get_vm_power_state) scoped to the selected VM's resource ID.

On new threads, also prepends pre-fetched evidence context from Cosmos so the
agent starts grounded. Function calling then lets it fetch additional live data
on demand as the conversation continues.
"""
import os

import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.foundry import (
    _CONVERSATION_HISTORY,
    _CONVERSATION_HISTORY_LIMIT,
    _get_domain_instructions,
    _get_openai_client,
)
from services.api_gateway.vm_chat_tools import VM_CHAT_TOOL_SCHEMAS, dispatch_tool_call

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
    reply: Optional[str] = None


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
        return _load_evidence(cosmos_client, items[0]["incident_id"])
    except Exception as exc:
        logger.debug("vm_chat: latest evidence lookup failed | resource=%s error=%s", resource_id[-60:], exc)
        return None


def _build_evidence_context(resource_id: str, evidence: Optional[dict]) -> str:
    """Build a context block prepended to the user message on new threads."""
    resource_name = resource_id.rstrip("/").split("/")[-1]

    if not evidence or not evidence.get("evidence_summary"):
        return (
            f"[VM Context] You are investigating Azure VM: {resource_name} ({resource_id}). "
            "No pre-fetched evidence available. Use diagnostic tools to gather data.\n\n"
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
        f"### Health State: {health_state}",
    ]

    if recent_changes:
        lines.append(f"### Recent Activity (last 2h) — {len(recent_changes)} events")
        for change in recent_changes[:5]:
            ts = change.get("timestamp", "")[:19].replace("T", " ")
            lines.append(f"- {ts}: {change.get('operation','')} by {change.get('caller','')} — {change.get('status','')}")
        if len(recent_changes) > 5:
            lines.append(f"- ... and {len(recent_changes) - 5} more events")
    else:
        lines.append("### Recent Activity: No activity log events in last 2h")

    if metric_anomalies:
        lines.append(f"### Metric Anomalies ({len(metric_anomalies)} detected)")
        for anomaly in metric_anomalies:
            lines.append(
                f"- {anomaly.get('metric_name','')}: {anomaly.get('current_value',0):.1f}"
                f"{anomaly.get('unit','')} (threshold: {anomaly.get('threshold',0)}{anomaly.get('unit','')})"
            )

    if log_errors.get("count", 0) > 0:
        lines.append(f"### Log Errors: {log_errors['count']} errors detected")
        for sample in (log_errors.get("sample") or [])[:3]:
            lines.append(f"  - {sample}")

    lines.append("---")
    lines.append("Use this context to guide your investigation. Propose remediation via propose_* tools — never execute directly.\n")
    return "\n".join(lines)


async def _dispatch_vm_chat(
    resource_id: str,
    request: VMChatRequest,
    cosmos_client: Any,
    user_id: str,
    credential: Any = None,
) -> dict[str, str]:
    """Dispatch a VM-scoped chat message with live function calling.

    Flow:
    1. Build system prompt (compute agent instructions + resource ID context)
    2. Prepend evidence context on new threads
    3. Replay conversation history for multi-turn continuity
    4. Call chat.completions with Azure SDK tool schemas
    5. Execute any tool calls the LLM requests (metrics, logs, health, power state)
    6. Feed tool results back → repeat until LLM returns a final text reply
    7. Persist turn to conversation history
    """
    loop = asyncio.get_running_loop()

    # Build user message — prepend evidence context on new threads
    user_message = request.message
    if not request.thread_id and cosmos_client:
        evidence = None
        if request.incident_id:
            evidence = await loop.run_in_executor(
                None, _load_evidence, cosmos_client, request.incident_id
            )
        if not evidence:
            evidence = await loop.run_in_executor(
                None, _load_latest_evidence_for_resource, cosmos_client, resource_id
            )
        context = _build_evidence_context(resource_id, evidence)
        user_message = context + request.message
        logger.info(
            "vm_chat: evidence context prepended | resource=%s evidence=%s",
            resource_id[-60:], "found" if evidence else "none",
        )

    # System prompt: compute specialist + explicit resource scope
    vm_name = resource_id.rstrip("/").split("/")[-1]
    _, base_instructions = _get_domain_instructions("compute_agent")
    system_prompt = (
        f"{base_instructions}\n\n"
        f"You are investigating a specific Azure VM:\n"
        f"  Name: {vm_name}\n"
        f"  Resource ID: {resource_id}\n\n"
        "You have live tools available to fetch real-time data for this VM. "
        "Use them whenever the user asks about metrics, logs, health, or power state. "
        "Do NOT say data is unavailable without first trying the relevant tool."
    )

    # Conversation history for multi-turn continuity
    history_key = request.thread_id or None
    prior_history = _CONVERSATION_HISTORY.get(history_key, []) if history_key else []

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(prior_history)
    messages.append({"role": "user", "content": user_message})

    openai_client = _get_openai_client()
    response_id = f"chat-{uuid.uuid4().hex[:16]}"

    # Tool-calling loop — max 5 rounds to prevent runaway calls
    MAX_TOOL_ROUNDS = 5
    reply: Optional[str] = None

    for _round in range(MAX_TOOL_ROUNDS):
        response = await loop.run_in_executor(
            None,
            lambda m=messages: openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=m,
                tools=VM_CHAT_TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=1500,
            ),
        )

        choice = response.choices[0]

        # Terminal: LLM returned a text reply
        if choice.finish_reason == "stop" or not choice.message.tool_calls:
            reply = choice.message.content
            break

        # LLM wants to call tools — execute each and feed results back
        messages.append(choice.message)  # assistant message with tool_calls

        for tool_call in choice.message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            logger.info("vm_chat: tool_call | tool=%s resource=%s", tool_name, resource_id[-60:])

            tool_result = await loop.run_in_executor(
                None,
                lambda tn=tool_name, ta=tool_args: dispatch_tool_call(
                    tool_name=tn,
                    tool_args=ta,
                    resource_id=resource_id,
                    credential=credential,
                ),
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result,
            })
    else:
        # Exhausted tool rounds — ask LLM for a summary with what it has
        messages.append({"role": "user", "content": "Please summarise your findings so far."})
        final = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=messages,
                max_tokens=1000,
            ),
        )
        reply = final.choices[0].message.content

    # Persist this turn into conversation history (plain text, not envelopes)
    new_history_key = history_key or response_id
    history = list(_CONVERSATION_HISTORY.get(new_history_key, []))
    history.append({"role": "user", "content": request.message})  # store plain user text
    history.append({"role": "assistant", "content": reply or ""})
    max_messages = _CONVERSATION_HISTORY_LIMIT * 2
    if len(history) > max_messages:
        history = history[-max_messages:]
    _CONVERSATION_HISTORY[new_history_key] = history

    logger.info(
        "vm_chat: complete | resource=%s thread=%s tool_rounds=%d reply_len=%d user=%s",
        resource_id[-60:], new_history_key, _round + 1, len(reply or ""), user_id,
    )

    return {
        "response_id": response_id,
        "thread_id": new_history_key,
        "run_id": response_id,
        "status": "completed",
        "reply": reply,
    }


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
    """Start or continue a resource-scoped VM investigation conversation.

    Routes through the orchestrator (which hands off to compute agent via
    connected_agent tools). On new threads, evidence context is prepended
    to the message so the agent is grounded immediately.
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
        result = await _dispatch_vm_chat(
            resource_id=resource_id,
            request=payload,
            cosmos_client=cosmos_client,
            user_id=user_id,
            credential=credential,
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
        reply=result.get("reply"),
    )
