from __future__ import annotations
"""Network Topology API endpoints — Phase 103.

Routes:
  GET  /api/v1/network-topology
  POST /api/v1/network-topology/path-check
  POST /api/v1/network-topology/chat

Data is queried live from Azure Resource Graph (15m TTL cache).
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential_for_subscriptions
from services.api_gateway.federation import resolve_subscription_ids
from services.api_gateway.network_topology_service import (
    evaluate_path_check,
    fetch_network_topology,
)
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
    protocol: str = "TCP"


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

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /network-topology → nodes=%d edges=%d issues=%d (%.0fms)",
        len(result.get("nodes", [])),
        len(result.get("edges", [])),
        len(result.get("issues", [])),
        duration_ms,
    )
    return result


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

        context_block = (
            f"[Topology Context] Subscription IDs: {', '.join(request.subscription_ids) or 'all'}. "
            f"Current graph: {node_count} nodes, {edge_count} edges."
        )
        if selected_node:
            context_block += f" Selected node: {selected_node}."

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
        accumulated = []

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

        # Persist conversation turn
        new_history_key = history_key or response_id
        history = list(_CONVERSATION_HISTORY.get(new_history_key, []))
        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": reply_text})
        max_messages = _CONVERSATION_HISTORY_LIMIT * 2
        if len(history) > max_messages:
            history = history[-max_messages:]
        _CONVERSATION_HISTORY[new_history_key] = history

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
