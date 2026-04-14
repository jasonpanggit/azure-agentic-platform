"""Chat endpoint — operator-initiated conversations (D-06, TEAMS-004).

Creates a Foundry thread for ad-hoc operator queries, separate
from detection-plane incident ingestion (POST /api/v1/incidents).
Supports thread continuation for cross-surface thread sharing (TEAMS-004).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from agents.shared.routing import classify_query_text

from services.api_gateway.arg_helper import run_arg_query
from services.api_gateway.foundry import _get_foundry_client, dispatch_chat_to_orchestrator
from services.api_gateway.instrumentation import agent_span, foundry_span, mcp_span
from services.api_gateway.models import ChatRequest

# ---------------------------------------------------------------------------
# In-memory result cache
# Maps response_id → {thread_id, run_status, reply}
# Populated by create_chat_thread; read by get_chat_result.
# The Responses API is synchronous so the result is available immediately.
# Using a simple dict — single process, no persistence required.
# ---------------------------------------------------------------------------
_RESPONSE_CACHE: dict[str, dict] = {}

logger = logging.getLogger(__name__)

# Build domain agent ID set from environment variables (populated by Terraform).
# Used by _approve_pending_subrun_mcp_calls to filter runs belonging to domain agents.
_DOMAIN_AGENT_IDS: frozenset[str] = frozenset(
    v for v in (
        os.environ.get("COMPUTE_AGENT_ID"),
        os.environ.get("NETWORK_AGENT_ID"),
        os.environ.get("STORAGE_AGENT_ID"),
        os.environ.get("SECURITY_AGENT_ID"),
        os.environ.get("SRE_AGENT_ID"),
        os.environ.get("ARC_AGENT_ID"),
        os.environ.get("PATCH_AGENT_ID"),
        os.environ.get("EOL_AGENT_ID"),
    )
    if v
)
if not _DOMAIN_AGENT_IDS:
    logger.warning(
        "No domain agent IDs configured via env vars "
        "(COMPUTE_AGENT_ID, NETWORK_AGENT_ID, ...). "
        "Sub-run MCP approval will be skipped."
    )


# ARG KQL: lightweight VM inventory for agent resource resolution.
# Only VMs — keeps thread context small. Agents use this to resolve
# "jumphost VM" → full resource ID without guessing the resource group.
_VM_INVENTORY_KQL = """
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| project
    id          = tolower(id),
    name,
    resourceGroup,
    location,
    subscriptionId
| order by name asc
"""


def _fetch_vm_inventory(credential: Any, subscription_ids: list[str]) -> list[dict]:
    """Fetch a lightweight VM inventory from ARG for agent grounding.

    Returns a list of {id, name, resourceGroup, location, subscriptionId} dicts.
    Returns [] on any error — resource context is best-effort, never blocks chat.
    """
    try:
        rows = run_arg_query(credential, subscription_ids, _VM_INVENTORY_KQL)
        return [
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "resourceGroup": r.get("resourceGroup", ""),
                "location": r.get("location", ""),
                "subscriptionId": r.get("subscriptionId", ""),
            }
            for r in rows
            if r.get("name")
        ]
    except Exception as exc:
        logger.warning("_fetch_vm_inventory: ARG query failed — agents will lack VM context | error=%s", exc)
        return []


def _build_operator_query_envelope(
    *,
    thread_id: str,
    request: ChatRequest,
    initiated_by: str,
    credential: Any = None,
) -> str:
    """Build a structured operator-query envelope for orchestrator routing."""
    classification = classify_query_text(request.message)
    payload: dict[str, object] = {
        "message": request.message,
        "initiated_by": initiated_by,
        "domain_hint": classification["domain"],
        "classification_confidence": classification["confidence"],
        "classification_reason": classification["reason"],
    }

    # Use provided subscription IDs, or fall back to the platform default subscription
    # so the orchestrator always has subscription context without asking the operator.
    subscription_ids = request.subscription_ids or []
    if not subscription_ids:
        default_sub = os.environ.get("DEFAULT_SUBSCRIPTION_ID")
        if default_sub:
            subscription_ids = [default_sub]
    if subscription_ids:
        payload["subscription_ids"] = subscription_ids

    # Inject VM inventory so all domain agents can resolve resource names to IDs
    # without guessing resource groups. Best-effort: skipped if ARG unavailable.
    if credential is not None:
        vms = _fetch_vm_inventory(credential, subscription_ids)
        if vms:
            payload["resource_context"] = {
                "virtual_machines": vms,
                "note": (
                    "Use 'id' from this list as the resource_id parameter when a user "
                    "refers to a VM by name. Never guess or fabricate a resource group."
                ),
            }

    envelope = {
        "correlation_id": request.incident_id or thread_id,
        "thread_id": thread_id,
        "source_agent": "api-gateway",
        "target_agent": "orchestrator",
        "message_type": "operator_query",
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(envelope)


async def _lookup_thread_by_incident(incident_id: str) -> Optional[str]:
    """Look up Foundry thread_id from Cosmos DB incident record."""
    try:
        from services.api_gateway.incidents_list import _get_incidents_container

        container = _get_incidents_container()
        query = "SELECT c.thread_id FROM c WHERE c.incident_id = @incident_id"
        items = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@incident_id", "value": incident_id}],
                enable_cross_partition_query=True,
            )
        )
        if items and items[0].get("thread_id"):
            return items[0]["thread_id"]
    except Exception as exc:
        logger.warning(
            "Failed to look up thread for incident %s: %s", incident_id, exc
        )
    return None


async def create_chat_thread(
    request: ChatRequest,
    user_id: str,
    credential: Any = None,
) -> dict[str, str]:
    """Dispatch an operator chat message to the Orchestrator via the Responses API.

    Replaces the threads/runs pattern (Phase 1-28) with a single synchronous
    Responses API call. The Responses API blocks until the agent completes,
    so the reply is available immediately — no polling required.

    Args:
        request: Validated chat request.
        user_id: Authenticated operator's user ID from Entra token.
        credential: Azure credential for ARG VM inventory lookup (best-effort).

    Returns:
        Dict with "thread_id", "run_id", "status", and "reply" keys.
        thread_id and run_id both map to the Foundry response ID.
    """
    effective_user_id = request.user_id or user_id

    # Build the operator query envelope (includes subscription context, VM inventory, domain hint)
    # Use the response_id as a synthetic thread_id for envelope construction
    import uuid as _uuid
    synthetic_thread_id = request.thread_id or str(_uuid.uuid4())

    loop = asyncio.get_running_loop()
    message_content = await loop.run_in_executor(
        None,
        lambda: _build_operator_query_envelope(
            thread_id=synthetic_thread_id,
            request=request,
            initiated_by=effective_user_id,
            credential=credential,
        ),
    )

    # Dispatch via Responses API — synchronous, returns final reply
    with agent_span("orchestrator", correlation_id=request.incident_id or ""):
        result = await dispatch_chat_to_orchestrator(
            message=message_content,
            conversation_id=request.thread_id,  # None for new conversations
        )

    response_id = result["response_id"]
    reply = result.get("reply")
    run_status = "completed" if result["status"] == "completed" else result["status"]

    # Cache the result so get_chat_result() can return it immediately
    _RESPONSE_CACHE[response_id] = {
        "thread_id": response_id,
        "run_status": run_status,
        "reply": reply,
    }

    logger.info(
        "Chat dispatched for user %s, response %s, status %s, reply_len %d",
        effective_user_id, response_id, run_status, len(reply) if reply else 0,
    )

    return {"thread_id": response_id, "run_id": response_id}


async def _submit_mcp_approval(
    endpoint: str,
    thread_id: str,
    run_id: str,
    tool_calls: list,
) -> bool:
    """Submit auto-approval for Foundry MCP tool calls via REST.

    The SDK doesn't expose submit_tool_approval; call the REST endpoint directly.
    Returns True on success.
    """
    import requests as _requests
    from azure.identity import DefaultAzureCredential

    approvals = [{"tool_call_id": tc.id, "approve": True} for tc in tool_calls]
    logger.info(
        "Auto-approving %d MCP tool call(s) for thread %s run %s",
        len(approvals), thread_id, run_id,
    )
    try:
        _token = DefaultAzureCredential().get_token("https://ai.azure.com/.default")
        _headers = {
            "Authorization": f"Bearer {_token.token}",
            "Content-Type": "application/json",
        }
        _url = f"{endpoint}/threads/{thread_id}/runs/{run_id}/submit_tool_outputs?api-version=2025-05-15-preview"
        _resp = _requests.post(_url, headers=_headers, json={"tool_approvals": approvals})
        if _resp.status_code in (200, 201):
            return True
        logger.warning("Failed to submit tool approvals: %s %s", _resp.status_code, _resp.text[:200])
    except Exception as exc:
        logger.warning("Exception submitting tool approvals: %s", exc)
    return False


def _approve_pending_subrun_mcp_calls(
    client: Any,
    endpoint: str,
    thread_id: str,
    run_id: str,
) -> None:
    """Find and handle pending action gates on domain-agent sub-runs.

    Handles two types of ``requires_action``:

    1. **submit_tool_approval** — MCP tool approval gates. Auto-approves all
       pending MCP tool calls so the domain agent can proceed.
    2. **submit_tool_outputs** — Function tool calls that need gateway-side
       execution. Executes each tool via ``tool_executor.execute_tool_call``
       and submits the results back to Foundry.

    Uses the Foundry REST API directly (NOT the SDK) because:
    - SDK's threads.list() ignores the limit parameter and returns ALL threads (~18s)
    - REST API with limit=5 returns in ~1.5s

    Strategy: list the 5 most recent threads, find any domain-agent runs with
    requires_action, and handle them by type.
    """
    import requests as _requests
    from azure.identity import DefaultAzureCredential

    if not _DOMAIN_AGENT_IDS:
        logger.debug("No domain agent IDs configured; skipping sub-run approval scan.")
        return

    try:
        _token = DefaultAzureCredential().get_token("https://ai.azure.com/.default")
    except Exception as exc:
        logger.warning("Could not get access token for approval: %s", exc)
        return

    headers = {
        "Authorization": f"Bearer {_token.token}",
        "Content-Type": "application/json",
    }
    api_ver = "2025-05-15-preview"

    # Get 5 most recent threads (fast: REST API with limit respected)
    try:
        r = _requests.get(
            f"{endpoint}/threads?api-version={api_ver}&limit=5",
            headers=headers, timeout=8
        )
        recent_threads = r.json().get("data") or []
    except Exception as exc:
        logger.warning("Could not list threads for approval: %s", exc)
        return

    for t in recent_threads:
        t_id = t.get("id")
        if not t_id or t_id == thread_id:
            continue  # Skip the orchestrator's own thread

        # Check runs on this thread for pending approval
        try:
            r2 = _requests.get(
                f"{endpoint}/threads/{t_id}/runs?api-version={api_ver}&limit=3",
                headers=headers, timeout=5
            )
            runs = r2.json().get("data") or []
        except Exception:
            continue

        for sub_run_data in runs:
            if sub_run_data.get("status") != "requires_action":
                continue
            if sub_run_data.get("assistant_id") not in _DOMAIN_AGENT_IDS:
                continue

            ra = sub_run_data.get("required_action") or {}
            ra_type = ra.get("type")
            sub_run_id = sub_run_data["id"]

            if ra_type == "submit_tool_approval":
                # MCP tool approval gate — auto-approve all pending calls
                tool_calls = (ra.get("submit_tool_approval") or {}).get("tool_calls", [])
                approvals = [{"tool_call_id": tc["id"], "approve": True} for tc in tool_calls]

                logger.info(
                    "Approving %d MCP tool call(s) for sub-run %s/%s",
                    len(approvals), t_id, sub_run_id,
                )
                try:
                    resp = _requests.post(
                        f"{endpoint}/threads/{t_id}/runs/{sub_run_id}/submit_tool_outputs"
                        f"?api-version={api_ver}",
                        headers=headers,
                        json={"tool_approvals": approvals},
                        timeout=10,
                    )
                    if resp.status_code in (200, 201):
                        logger.info("Approved MCP sub-run %s", sub_run_id)
                    else:
                        logger.warning(
                            "Failed to approve sub-run %s: %s %s",
                            sub_run_id, resp.status_code, resp.text[:200],
                        )
                except Exception as exc:
                    logger.warning("Exception approving sub-run %s: %s", sub_run_id, exc)

            elif ra_type == "submit_tool_outputs":
                # Function tool calls — execute locally and return results
                from services.api_gateway.tool_executor import execute_tool_call

                tool_calls = (ra.get("submit_tool_outputs") or {}).get("tool_calls", [])
                tool_outputs = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    fn_args_raw = fn.get("arguments", "{}")
                    tc_id = tc.get("id", "")
                    logger.info(
                        "Executing function tool %s for sub-run %s/%s",
                        fn_name, t_id, sub_run_id,
                    )
                    output = execute_tool_call(fn_name, fn_args_raw)
                    tool_outputs.append({"tool_call_id": tc_id, "output": output})

                logger.info(
                    "Submitting %d tool output(s) for sub-run %s/%s",
                    len(tool_outputs), t_id, sub_run_id,
                )
                try:
                    resp = _requests.post(
                        f"{endpoint}/threads/{t_id}/runs/{sub_run_id}/submit_tool_outputs"
                        f"?api-version={api_ver}",
                        headers=headers,
                        json={"tool_outputs": tool_outputs},
                        timeout=30,
                    )
                    if resp.status_code in (200, 201):
                        logger.info("Submitted tool outputs for sub-run %s", sub_run_id)
                    else:
                        logger.warning(
                            "Failed to submit tool outputs for sub-run %s: %s %s",
                            sub_run_id, resp.status_code, resp.text[:200],
                        )
                except Exception as exc:
                    logger.warning("Exception submitting tool outputs for sub-run %s: %s", sub_run_id, exc)



async def get_chat_result(
    thread_id: str, run_id: Optional[str] = None
) -> dict[str, str]:
    """Return the result of a Responses API chat call (single-shot, non-blocking).

    Since create_chat_thread() now uses the synchronous Responses API, the
    result is cached immediately in _RESPONSE_CACHE. This function simply
    looks up the cache by response_id (passed as thread_id/run_id).

    The SSE stream route polls this endpoint every 2s. On the first poll
    after create_chat_thread returns, the cache hit delivers the completed
    reply immediately — no polling loop needed.

    Args:
        thread_id: Foundry response ID (returned as thread_id by create_chat_thread).
        run_id: Same as thread_id for Responses API (ignored; thread_id is authoritative).

    Returns:
        Dict with "thread_id", "run_status", and optionally "reply".
    """
    lookup_id = run_id or thread_id
    cached = _RESPONSE_CACHE.get(lookup_id) or _RESPONSE_CACHE.get(thread_id)
    if cached:
        logger.debug("Cache hit for response %s: status=%s", lookup_id, cached["run_status"])
        return cached

    # No cache entry — the response may still be in-flight (create_chat_thread
    # is awaited by the POST handler before SSE connects, so this should be rare).
    # Return in_progress so the SSE retries on next cycle.
    logger.debug("No cache entry for %s — returning in_progress", lookup_id)
    return {"thread_id": thread_id, "run_status": "in_progress", "reply": None}


# ---------------------------------------------------------------------------
# Legacy helpers — kept for backward-compat with approvals and Teams bot
# These used the old threads/runs pattern. They are no longer called by
# the main chat flow but may still be referenced by other modules.
# ---------------------------------------------------------------------------

