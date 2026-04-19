from __future__ import annotations
"""Network Topology API endpoints — Phase 103 / 108-3.

Routes:
  GET  /api/v1/network-topology
  POST /api/v1/network-topology/path-check
  POST /api/v1/network-topology/chat
  POST /api/v1/network-topology/remediate
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.network_topology_service import (
    evaluate_path_check,
    fetch_network_topology,
)
from services.api_gateway.network_topology_ai import (
    get_ai_issues,
    trigger_ai_analysis,
)
from services.api_gateway import arg_cache
from services.api_gateway.network_remediation import (
    SAFE_NETWORK_ACTIONS,
    execute_network_remediation,
)
from services.api_gateway.approvals import create_approval
from services.api_gateway.foundry import (
    _CONVERSATION_HISTORY,
    _CONVERSATION_HISTORY_LIMIT,
    _get_domain_instructions,
    _get_openai_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/network-topology", tags=["network-topology"])


class PathCheckRequest(BaseModel):
    """Request body for NSG path check evaluation."""

    source_resource_id: str
    destination_resource_id: str
    port: int = Field(ge=1, le=65535)
    protocol: Literal["TCP", "UDP", "ICMP", "*"] = "TCP"


class RemediateRequest(BaseModel):
    """Request body for network issue remediation."""

    issue_id: str = Field(min_length=16, max_length=16, pattern=r'^[0-9a-f]{16}$')
    subscription_id: Optional[str] = None
    require_approval: bool = False


class RemediateResponse(BaseModel):
    """Response from network remediation endpoint."""

    status: str  # "executed" | "approval_pending" | "error"
    message: str
    approval_id: Optional[str] = None
    execution_id: Optional[str] = None


@router.get("")
async def get_topology(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Return network topology graph queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = fetch_network_topology(subscription_ids, credential=credential)

    # Phase 109: kick off async AI analysis (fire-and-forget)
    trigger_ai_analysis(subscription_ids, result)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /network-topology → nodes=%d edges=%d issues=%d (%.0fms)",
        len(result.get("nodes", [])),
        len(result.get("edges", [])),
        len(result.get("issues", [])),
        duration_ms,
    )
    return result


@router.get("/ai-issues")
async def get_ai_issues_endpoint(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
) -> Dict[str, Any]:
    """Return AI-detected network issues from the async analysis layer.

    Returns {"status": "pending"|"ready"|"error", "issues": [...], "error": str|None}.
    The client polls this endpoint every 3s after loading topology until status == "ready".
    Issues have source="ai" and IDs prefixed with "ai-".
    """
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = get_ai_issues(subscription_ids)
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /network-topology/ai-issues → status=%s issues=%d (%.0fms)",
        result.get("status"), len(result.get("issues", [])), duration_ms,
    )
    return result


@router.post("/remediate", response_model=RemediateResponse)
async def remediate_issue(
    body: RemediateRequest,
    request: Request,
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> RemediateResponse:
    """Execute auto-fix or submit HITL approval for a detected network issue.

    Safe auto-fix types (no approval required unless require_approval=True):
      - firewall_threatintel_off
      - pe_not_approved

    All other issue types route to the HITL approval queue.
    """
    start_time = time.monotonic()

    # Resolve subscription list for topology lookup
    subscription_ids = resolve_subscription_ids(body.subscription_id, request)

    # Look up the issue from the cached topology
    topology = fetch_network_topology(subscription_ids, credential=credential)
    issues: List[Dict[str, Any]] = topology.get("issues", [])
    issue = next((i for i in issues if i.get("id") == body.issue_id), None)

    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{body.issue_id}' not found in topology")

    issue_type: str = issue.get("type", "")
    is_safe = issue_type in SAFE_NETWORK_ACTIONS

    try:
        # Route to approval queue when explicitly requested or issue is not auto-fixable
        if body.require_approval or not is_safe:
            risk_level = "low" if is_safe else "high"
            approval = await create_approval(
                thread_id="network-topology",
                incident_id=body.issue_id,
                agent_name="network-topology",
                proposal={
                    "action": issue.get("auto_fix_label") or "Manual remediation",
                    "issue": issue,
                },
                resource_snapshot={"affected_resource_id": issue.get("affected_resource_id", "")},
                risk_level=risk_level,
                credential=credential,
            )
            approval_id = approval.get("id", "") if isinstance(approval, dict) else ""
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "POST /network-topology/remediate → approval_pending | "
                "issue_id=%s issue_type=%s approval_id=%s (%.0fms)",
                body.issue_id, issue_type, approval_id, duration_ms,
            )
            return RemediateResponse(
                status="approval_pending",
                message="Approval request submitted. Check the Approval Queue in Observability tab.",
                approval_id=approval_id,
            )

        # Auto-fix path
        result = await execute_network_remediation(
            issue=issue,
            subscription_id=subscription_ids[0] if subscription_ids else "",
            credential=credential,
        )

        if result.get("status") == "executed":
            # Invalidate topology cache so next fetch returns fresh data
            arg_cache.invalidate("network_topology")

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "POST /network-topology/remediate → %s | "
            "issue_id=%s issue_type=%s execution_id=%s (%.0fms)",
            result.get("status"), body.issue_id, issue_type,
            result.get("execution_id"), duration_ms,
        )

        if result.get("status") == "error":
            return RemediateResponse(
                status="error",
                message=result.get("message", "Remediation failed"),
                execution_id=result.get("execution_id"),
            )

        return RemediateResponse(
            status="executed",
            message=result.get("message", "Fix applied successfully."),
            execution_id=result.get("execution_id"),
        )

    except HTTPException:
        raise
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "POST /network-topology/remediate: unhandled error | "
            "issue_id=%s error=%s (%.0fms)",
            body.issue_id, exc, duration_ms,
        )
        return RemediateResponse(
            status="error",
            message=str(exc),
        )


class NetworkChatRequest(BaseModel):
    """Request body for network topology AI chat."""

    message: str
    subscription_ids: List[str] = Field(default_factory=list)
    thread_id: Optional[str] = None
    topology_context: Optional[Dict[str, Any]] = None  # {node_count, edge_count, selected_node_id}


async def _stream_network_chat(
    request: NetworkChatRequest,
    user_id: str,
) -> AsyncIterator[str]:
    """Generate SSE token stream from the network agent.

    Yields: data: {"token": "..."} chunks, terminated by data: [DONE]
    Never raises — errors are yielded as data: {"error": "..."} followed by data: [DONE].
    """
    start_time = time.monotonic()
    loop = asyncio.get_running_loop()

    try:
        _, base_instructions = _get_domain_instructions("network_agent")

        # Build context-enriched system prompt
        ctx = request.topology_context or {}
        node_count = ctx.get("node_count", "unknown")
        edge_count = ctx.get("edge_count", "unknown")
        selected_node = ctx.get("selected_node_id")

        # Sanitise user-controlled context values to prevent prompt injection.
        # Strip newlines, angle brackets, and truncate to a safe length.
        def _sanitise_context(value: str, max_len: int = 200) -> str:
            sanitised = value.replace("\n", " ").replace("\r", " ").replace("<", "").replace(">", "")
            return sanitised[:max_len]

        safe_subscription_ids = [
            _sanitise_context(s) for s in request.subscription_ids
        ]
        safe_selected_node = _sanitise_context(str(selected_node)) if selected_node else None

        context_block = (
            f"[Topology Context] Subscription IDs: {', '.join(safe_subscription_ids) or 'all'}. "
            f"Current graph: {node_count} nodes, {edge_count} edges."
        )
        if safe_selected_node:
            context_block += f" Selected node: {safe_selected_node}."

        system_prompt = f"{base_instructions}\n\n{context_block}"

        # Conversation history for multi-turn continuity
        history_key = request.thread_id or None
        prior_history = _CONVERSATION_HISTORY.get(history_key, []) if history_key else []

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(prior_history)
        messages.append({"role": "user", "content": request.message})

        openai_client = _get_openai_client()
        response_id = f"net-chat-{uuid.uuid4().hex[:16]}"

        # Run streaming completion in executor to avoid blocking the event loop

        def _do_stream() -> list[str]:
            tokens: list[str] = []
            with openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=messages,
                max_tokens=1500,
                stream=True,
            ) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        tokens.append(delta.content)
            return tokens

        tokens = await loop.run_in_executor(None, _do_stream)

        reply_text = ""
        for token in tokens:
            reply_text += token
            yield f"data: {json.dumps({'token': token})}\n\n"

        # Persist conversation turn with LRU eviction on the global dict.
        # Cap total keys to _CONVERSATION_HISTORY_LIMIT to prevent unbounded memory growth.
        _CONVERSATION_HISTORY_MAX_THREADS = 500
        new_history_key = history_key or response_id
        history = list(_CONVERSATION_HISTORY.get(new_history_key, []))
        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": reply_text})
        max_messages = _CONVERSATION_HISTORY_LIMIT * 2
        if len(history) > max_messages:
            history = history[-max_messages:]
        _CONVERSATION_HISTORY[new_history_key] = history
        # Evict oldest entries when the global dict exceeds the thread cap
        while len(_CONVERSATION_HISTORY) > _CONVERSATION_HISTORY_MAX_THREADS:
            oldest_key = next(iter(_CONVERSATION_HISTORY))
            del _CONVERSATION_HISTORY[oldest_key]

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "network_chat: complete | thread=%s user=%s reply_len=%d (%.0fms)",
            new_history_key, user_id, len(reply_text), duration_ms,
        )

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error("network_chat: failed | user=%s error=%s (%.0fms)", user_id, exc, duration_ms, exc_info=True)
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/chat")
async def network_chat(
    body: NetworkChatRequest,
    request: Request,
    token: Dict[str, Any] = Depends(verify_token),
) -> StreamingResponse:
    """Stream a network topology AI chat response via SSE.

    Connects directly to the network domain agent (no orchestrator hop).
    Thread history is in-memory (session-only — no Cosmos writes).
    """
    user_id = token.get("sub", "anonymous")
    logger.info(
        "POST /network-topology/chat | user=%s new_thread=%s",
        user_id, not body.thread_id,
    )

    return StreamingResponse(
        _stream_network_chat(body, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/path-check")
async def path_check(
    body: PathCheckRequest,
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential_for_subscriptions),
) -> Dict[str, Any]:
    """Evaluate NSG rule chain for source->destination traffic. On-demand, not cached."""
    start_time = time.monotonic()

    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = evaluate_path_check(
        source_resource_id=body.source_resource_id,
        destination_resource_id=body.destination_resource_id,
        port=body.port,
        protocol=body.protocol,
        subscription_ids=subscription_ids,
        credential=credential,
    )

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "POST /network-topology/path-check → verdict=%s (%.0fms)",
        result.get("verdict", "unknown"),
        duration_ms,
    )
    return result
