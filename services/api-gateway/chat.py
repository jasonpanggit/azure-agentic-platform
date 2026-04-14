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
from services.api_gateway.foundry import _get_foundry_client
from services.api_gateway.instrumentation import agent_span, foundry_span, mcp_span
from services.api_gateway.models import ChatRequest

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
    """Create or continue a Foundry thread for an operator chat session.

    Supports three modes (TEAMS-004):
    1. thread_id provided: Continue existing thread (skip creation).
    2. incident_id provided (no thread_id): Look up thread from Cosmos DB.
    3. Neither provided: Create a new Foundry thread (default).

    All synchronous Foundry SDK calls and ARG queries are offloaded to
    the default thread pool via run_in_executor to avoid blocking the
    async event loop (fixes chat timeout — event loop starvation).

    Args:
        request: Validated chat request.
        user_id: Authenticated operator's user ID from Entra token.
        credential: Azure credential for ARG VM inventory lookup (best-effort).

    Returns:
        Dict with "thread_id" and "run_id" keys.
    """
    loop = asyncio.get_running_loop()
    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID")

    if not orchestrator_agent_id:
        raise ValueError("ORCHESTRATOR_AGENT_ID environment variable is required.")

    # Determine user identity -- request.user_id takes precedence (D-07)
    effective_user_id = request.user_id or user_id

    # Resolve thread_id (TEAMS-004)
    thread_id = request.thread_id

    if not thread_id and request.incident_id:
        # Look up thread_id from Cosmos DB incident record
        thread_id = await _lookup_thread_by_incident(request.incident_id)

    if thread_id:
        # Continue existing thread (TEAMS-004)
        # Cancel any active runs first — Foundry rejects new messages on a thread
        # that has an in-progress run (raises HttpResponseError).
        logger.info("Continuing thread %s for user %s", thread_id, effective_user_id)
        try:
            runs = await loop.run_in_executor(
                None, lambda: list(client.runs.list(thread_id=thread_id))
            )
            active_statuses = {"queued", "in_progress", "requires_action", "cancelling"}
            for run in runs:
                if run.status in active_statuses:
                    logger.info(
                        "Cancelling active run %s (status=%s) on thread %s",
                        run.id,
                        run.status,
                        thread_id,
                    )
                    try:
                        await loop.run_in_executor(
                            None,
                            lambda r=run: client.runs.cancel(thread_id=thread_id, run_id=r.id),
                        )
                    except Exception as cancel_exc:
                        logger.warning("Failed to cancel run %s: %s", run.id, cancel_exc)
            # Brief wait for cancellation to propagate
            if runs and any(r.status in active_statuses for r in runs):
                await asyncio.sleep(2)
                # Verify the run is no longer active before proceeding
                for attempt in range(3):
                    try:
                        updated_runs = await loop.run_in_executor(
                            None, lambda: list(client.runs.list(thread_id=thread_id))
                        )
                        still_active = [r for r in updated_runs if r.status in active_statuses]
                        if not still_active:
                            break
                        logger.info(
                            "Thread %s still has %d active run(s) after cancellation, waiting... (attempt %d/3)",
                            thread_id, len(still_active), attempt + 1,
                        )
                        await asyncio.sleep(2)
                    except Exception:
                        break
        except Exception as list_exc:
            logger.warning("Failed to list/cancel runs for thread %s: %s", thread_id, list_exc)
    else:
        # Create new thread (sync SDK call — offloaded to thread pool)
        with foundry_span("create_thread") as span:
            thread = await loop.run_in_executor(None, client.threads.create)
            thread_id = thread.id
            span.set_attribute("foundry.thread_id", thread_id)
        logger.info(
            "Created chat thread %s for user %s", thread_id, effective_user_id
        )

    # Build envelope — _build_operator_query_envelope calls _fetch_vm_inventory
    # which does a synchronous ARG HTTP query. Offload to thread pool.
    message_content = await loop.run_in_executor(
        None,
        lambda: _build_operator_query_envelope(
            thread_id=thread_id,
            request=request,
            initiated_by=effective_user_id,
            credential=credential,
        ),
    )

    with foundry_span("post_message", thread_id=thread_id) as span:
        await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                thread_id=thread_id,
                role="user",
                content=message_content,
            ),
        )

    with agent_span("orchestrator", correlation_id=request.incident_id or ""):
        with foundry_span("create_run", thread_id=thread_id) as span:
            run = await loop.run_in_executor(
                None,
                lambda: client.runs.create(
                    thread_id=thread_id,
                    agent_id=orchestrator_agent_id,
                ),
            )
            span.set_attribute("foundry.run_id", run.id)

    return {"thread_id": thread_id, "run_id": run.id}


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
    """Return the current status of a Foundry run (single-shot, non-blocking).

    Called repeatedly by the SSE stream route which owns the polling loop.
    This function fetches the run once and returns immediately — it does NOT
    block waiting for completion.

    All synchronous Foundry SDK calls are offloaded to the default thread
    pool via run_in_executor to avoid blocking the async event loop
    (fixes chat timeout — event loop starvation).

    Args:
        thread_id: Foundry thread ID.
        run_id: Specific run ID to poll.

    Returns:
        Dict with "thread_id", "run_status", and optionally "reply".
    """
    loop = asyncio.get_running_loop()
    client = _get_foundry_client()
    terminal = {"completed", "failed", "cancelled", "expired"}

    # Fetch the target run (sync SDK call — offloaded to thread pool).
    # Foundry's run-status API can be slow under load; wrap with a 12s asyncio
    # timeout so this endpoint always returns quickly and the SSE poll never
    # hits its own AbortSignal.timeout before we respond.
    # On timeout we return in_progress so the SSE route retries next cycle.
    if run_id:
        # Specific run requested — fetch directly
        try:
            latest_run = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.runs.get(thread_id=thread_id, run_id=run_id),
                ),
                timeout=12,
            )
        except asyncio.TimeoutError:
            logger.warning("Run %s status poll timed out (Foundry slow) — returning in_progress", run_id)
            return {"thread_id": thread_id, "run_status": "in_progress", "reply": None}
        except Exception as exc:
            logger.warning("Run %s not found: %s", run_id, exc)
            return {"thread_id": thread_id, "run_status": "not_found", "reply": None}
    else:
        # No run_id — list all runs and pick the most recent (last in list)
        try:
            run_list = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: list(client.runs.list(thread_id=thread_id)),
                ),
                timeout=12,
            )
        except asyncio.TimeoutError:
            logger.warning("Run list for thread %s timed out — returning in_progress", thread_id)
            return {"thread_id": thread_id, "run_status": "in_progress", "reply": None}
        if not run_list:
            return {"thread_id": thread_id, "run_status": "not_found", "reply": None}
        latest_run = run_list[-1]

    # Status may be a string (SDK 1.2.x) or an enum with .value (older SDK)
    _s = latest_run.status
    run_status = _s if isinstance(_s, str) else str(getattr(_s, "value", _s))

    logger.debug("Thread %s run %s status: %s", thread_id, latest_run.id, run_status)

    # If requires_action, auto-approve MCP tool calls so run can proceed
    if run_status == "requires_action":
        required_action = latest_run.required_action
        if (
            required_action is not None
            and hasattr(required_action, "type")
            and required_action.type == "submit_tool_outputs"
        ):
            tool_calls = required_action.submit_tool_outputs.tool_calls  # type: ignore[attr-defined]
            tool_outputs = []
            for tc in tool_calls:
                fn_name = getattr(tc.function, "name", "") if hasattr(tc, "function") else ""
                fn_args_raw = getattr(tc.function, "arguments", "{}") if hasattr(tc, "function") else "{}"
                logger.info("Executing function tool call: %s (id=%s)", fn_name, tc.id)

                if fn_name == "azure_tools":
                    # The orchestrator MUST NOT execute Azure tools directly.
                    # It is only allowed to classify incidents and route to domain
                    # agents via HandoffOrchestrator. Returning an error here
                    # forces the LLM to route to the correct domain agent instead
                    # of answering from raw Azure data.
                    fn_args = {}
                    try:
                        fn_args = json.loads(fn_args_raw)
                    except Exception:
                        pass
                    tool_name = fn_args.get("tool_name", "unknown")
                    logger.warning(
                        "Orchestrator attempted to call azure_tools(%s) directly — blocked. "
                        "Route to the appropriate domain agent instead.",
                        tool_name,
                    )
                    output = (
                        "ERROR: The orchestrator is not permitted to call Azure tools directly. "
                        "You MUST route this request to the appropriate domain agent "
                        "(compute-agent, network-agent, storage-agent, security-agent, "
                        "arc-agent, or sre-agent) via HandoffOrchestrator. "
                        "Do NOT answer from your own knowledge or tool calls."
                    )
                else:
                    output = f"Unknown function: {fn_name}"

                tool_outputs.append({"tool_call_id": tc.id, "output": output})

            logger.info(
                "Submitting %d tool output(s) for thread %s run %s",
                len(tool_outputs),
                thread_id,
                latest_run.id,
            )
            try:
                with mcp_span("tool_approval", thread_id=thread_id) as mspan:
                    mspan.set_attribute("mcp.tool_calls_count", str(len(tool_outputs)))
                    _run_id = latest_run.id
                    await loop.run_in_executor(
                        None,
                        lambda: client.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=_run_id,
                            tool_outputs=tool_outputs,
                        ),
                    )
            except Exception as exc:
                logger.warning("Failed to submit tool outputs: %s", exc)

    # Return non-terminal status immediately — caller polls again.
    # Sub-run MCP approval is handled by the endpoint in main.py via
    # FastAPI background_tasks (runs after response, never blocks here).
    if run_status not in terminal:
        return {"thread_id": thread_id, "run_status": run_status, "reply": None}

    reply = None
    if run_status == "completed":
        with foundry_span("list_messages", thread_id=thread_id):
            messages = await loop.run_in_executor(
                None,
                lambda: client.messages.list(thread_id=thread_id),
            )
        for msg in messages:
            if msg.role == "assistant":
                for block in msg.content:
                    if hasattr(block, "text") and hasattr(block.text, "value"):
                        reply = block.text.value
                        break
                if reply:
                    break

    return {"thread_id": thread_id, "run_status": run_status, "reply": reply}
