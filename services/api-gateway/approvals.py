from __future__ import annotations
"""Approval endpoints — HITL gate for remediation proposals (REMEDI-002, REMEDI-003, REMEDI-005).

Handles approval lifecycle: read, approve, reject with ETag concurrency.
Expired proposals return 410 Gone. Thread resume on approval callback.
"""
import os

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from azure.cosmos import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from fastapi import HTTPException

from services.api_gateway.instrumentation import agent_span, foundry_span
from services.api_gateway.remediation_logger import (
    build_remediation_event,
    log_remediation_event,
)

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_MINUTES = int(os.environ.get("APPROVAL_TIMEOUT_MINUTES", "30"))


def _get_approvals_container(cosmos_client: Optional[CosmosClient] = None) -> ContainerProxy:
    """Get the Cosmos DB approvals container.

    Uses the provided cosmos_client singleton when available; falls back to
    creating a per-call client for backward compatibility.
    """
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    database = cosmos_client.get_database_client(database_name)
    return database.get_container_client("approvals")


def _is_expired(record: dict) -> bool:
    """Check if an approval record has expired."""
    expires_at = datetime.fromisoformat(record["expires_at"])
    return datetime.now(timezone.utc) > expires_at


async def create_approval(
    thread_id: str,
    incident_id: str,
    agent_name: str,
    proposal: dict,
    resource_snapshot: dict,
    risk_level: str,
    timeout_minutes: Optional[int] = None,
    cosmos_client: Optional[CosmosClient] = None,
    topology_client: Optional[Any] = None,
    credential: Optional[Any] = None,
) -> dict:
    """Create a pending approval record in Cosmos DB.

    Used by POST /api/v1/approvals for synthetic approval injection (ops/demos).
    Matches the schema produced by agents/shared/approval_manager.py so the
    UI ProposalCard renders identically.

    Phase 51: Checks for policy auto-approval BEFORE creating the HITL pending record.
    If a policy matches all guards, executes immediately and returns auto_approved status.
    Falls through to HITL on any policy evaluation error (conservative).
    """
    # --- Phase 51: Policy auto-approval check ---
    try:
        from services.api_gateway.policy_engine import evaluate_auto_approval
        from services.api_gateway.remediation_executor import execute_remediation

        # Extract resource tags from the resource_snapshot
        resource_tags = {}
        if resource_snapshot:
            resource_tags = resource_snapshot.get("tags", {}) or {}

        # Extract resource_id and action_class from proposal
        target_resources = proposal.get("target_resources", [])
        resource_id = target_resources[0] if target_resources else ""
        action_class = proposal.get("action", "")

        if resource_id and action_class:
            auto_approved, policy_id, reason = await evaluate_auto_approval(
                action_class=action_class,
                resource_id=resource_id,
                resource_tags=resource_tags,
                topology_client=topology_client,
                cosmos_client=cosmos_client,
                credential=credential,
            )
            if auto_approved and policy_id:
                logger.info(
                    "create_approval: auto-approved by policy | "
                    "policy_id=%s action_class=%s resource_id=%s",
                    policy_id, action_class, resource_id,
                )
                now = datetime.now(timezone.utc)
                # Synthesize approval record for execute_remediation
                synthesized_record = {
                    "thread_id": thread_id,
                    "incident_id": incident_id,
                    "agent_name": agent_name,
                    "status": "approved",
                    "risk_level": risk_level,
                    "proposed_at": now.isoformat(),
                    "decided_at": now.isoformat(),
                    "decided_by": f"policy:{policy_id}",
                    "resource_snapshot": resource_snapshot,
                    "proposal": proposal,
                    "auto_approved_by_policy": policy_id,
                }
                # Execute directly, bypassing HITL
                result = await execute_remediation(
                    approval_id=f"auto-policy-{policy_id}",
                    credential=credential,
                    cosmos_client=cosmos_client,
                    topology_client=topology_client,
                    approval_record=synthesized_record,
                )
                return {
                    "approval_id": f"auto-policy-{policy_id}",
                    "status": "auto_approved",
                    "policy_id": policy_id,
                    "execution_result": result,
                }
    except Exception as exc:
        logger.warning(
            "create_approval: policy evaluation failed (falling through to HITL) | error=%s",
            exc,
        )
    # --- End Phase 51 ---

    now = datetime.now(timezone.utc)
    effective_timeout = timeout_minutes if timeout_minutes is not None else APPROVAL_TIMEOUT_MINUTES
    expires_at = now + timedelta(minutes=effective_timeout)

    record: dict[str, Any] = {
        "id": f"appr_{uuid.uuid4()}",
        "action_id": f"act_{uuid.uuid4()}",
        "thread_id": thread_id,
        "incident_id": incident_id,
        "agent_name": agent_name,
        "status": "pending",
        "risk_level": risk_level,
        "proposed_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "decided_at": None,
        "decided_by": None,
        "executed_at": None,
        "abort_reason": None,
        "resource_snapshot": resource_snapshot,
        "proposal": proposal,
    }

    container = _get_approvals_container(cosmos_client=cosmos_client)
    logger.info(
        "cosmos: creating approval | id=%s incident_id=%s thread_id=%s risk=%s",
        record["id"], incident_id, thread_id, risk_level,
    )
    created = container.create_item(body=record)
    logger.info("cosmos: approval created | id=%s", record["id"])
    return created


async def get_approval(approval_id: str, thread_id: str, cosmos_client: Optional[CosmosClient] = None) -> dict:
    """Read an approval record from Cosmos DB."""
    container = _get_approvals_container(cosmos_client=cosmos_client)
    logger.info("cosmos: reading approval | approval_id=%s thread_id=%s", approval_id, thread_id)
    try:
        doc = container.read_item(item=approval_id, partition_key=thread_id)
        logger.info("cosmos: approval read | approval_id=%s status=%s", approval_id, doc.get("status"))
        return doc
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Approval not found")


async def list_approvals_for_thread(thread_id: str, cosmos_client: Optional[CosmosClient] = None) -> list[dict]:
    """List all approval records for a thread."""
    container = _get_approvals_container(cosmos_client=cosmos_client)
    query = "SELECT * FROM c WHERE c.thread_id = @thread_id"
    items = container.query_items(
        query=query,
        parameters=[{"name": "@thread_id", "value": thread_id}],
        partition_key=thread_id,
    )
    return list(items)


async def list_approvals_by_status(status_filter: str = "pending", cosmos_client: Optional[CosmosClient] = None) -> list[dict]:
    """List all approval records matching the given status (TEAMS-005).

    Cross-partition query -- acceptable for small pending approval counts.
    Used by the Teams bot escalation scheduler.
    """
    container = _get_approvals_container(cosmos_client=cosmos_client)
    query = "SELECT * FROM c WHERE c.status = @status ORDER BY c.proposed_at ASC"
    items = container.query_items(
        query=query,
        parameters=[{"name": "@status", "value": status_filter}],
        enable_cross_partition_query=True,
    )
    return list(items)


async def process_approval_decision(
    approval_id: str,
    thread_id: str,
    decision: str,  # "approved" or "rejected"
    decided_by: str,
    scope_confirmed: Optional[bool] = None,
    feedback_text: Optional[str] = None,
    feedback_tags: Optional[list[str]] = None,
    cosmos_client: Optional[CosmosClient] = None,
) -> dict:
    """Process an approve/reject decision on a pending proposal.

    Enforces:
    - ETag optimistic concurrency (REMEDI-003)
    - 30-minute expiry — returns 410 Gone for expired (D-13)
    - Only "pending" records can be decided
    """
    container = _get_approvals_container(cosmos_client=cosmos_client)
    try:
        record = container.read_item(item=approval_id, partition_key=thread_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Approval not found")
    etag = record["_etag"]
    logger.info(
        "cosmos: approval fetched for decision | approval_id=%s status=%s decision=%s",
        approval_id,
        record.get("status"),
        decision,
    )

    # Check expiry (D-13)
    if _is_expired(record):
        now = datetime.now(timezone.utc).isoformat()
        expired_record = {
            **record,
            "status": "expired",
            "decided_at": now,
        }
        container.replace_item(
            item=approval_id,
            body=expired_record,
            etag=etag,
            match_condition="IfMatch",
        )
        # REMEDI-007: Log expired event to OneLake
        try:
            expired_event = build_remediation_event(
                approval_record=expired_record,
                outcome="expired",
            )
            await log_remediation_event(expired_event)
        except Exception as exc:
            logger.error("Expired event logging failed (non-blocking): %s", exc)
        raise ValueError("expired")

    # Only pending can be decided
    if record["status"] != "pending":
        raise ValueError(f"Cannot {decision} a record in status: {record['status']}")

    # Prod scope confirmation check (REMEDI-006)
    prod_subscriptions = os.environ.get("PROD_SUBSCRIPTION_IDS", "").split(",")
    if prod_subscriptions and prod_subscriptions != [""]:
        target_resources = record.get("proposal", {}).get("target_resources", [])
        for resource_id in target_resources:
            for prod_sub in prod_subscriptions:
                if prod_sub and prod_sub in resource_id:
                    if not scope_confirmed:
                        raise ValueError("scope_confirmation_required")

    now = datetime.now(timezone.utc).isoformat()
    updated_record = {
        **record,
        "status": decision,
        "decided_at": now,
        "decided_by": decided_by,
    }
    if feedback_text is not None:
        updated_record["feedback_text"] = feedback_text
    if feedback_tags is not None:
        updated_record["feedback_tags"] = feedback_tags

    result = container.replace_item(
        item=approval_id,
        body=updated_record,
        etag=etag,
        match_condition="IfMatch",
    )
    logger.info(
        "cosmos: approval updated | approval_id=%s status=%s decided_by=%s",
        approval_id,
        decision,
        decided_by,
    )

    # REMEDI-007: Log remediation event to OneLake (fire-and-forget)
    try:
        remediation_event = build_remediation_event(
            approval_record=updated_record,
            outcome=decision,  # "approved" or "rejected"
            correlation_id="",
        )
        await log_remediation_event(remediation_event)
    except Exception as exc:
        logger.error("Remediation event logging failed (non-blocking): %s", exc)

    # If approved, resume the Foundry thread
    if decision == "approved":
        try:
            await _resume_foundry_thread(
                thread_id=thread_id,
                approval_id=approval_id,
                decided_by=decided_by,
            )
        except Exception as exc:
            logger.error("Failed to resume Foundry thread %s: %s", thread_id, exc)

    return result


async def _resume_foundry_thread(
    thread_id: str,
    approval_id: str,
    decided_by: str,
) -> None:
    """Resume a parked Foundry thread after approval (D-10)."""
    from services.api_gateway.foundry import _get_foundry_client

    client = _get_foundry_client()
    orchestrator_agent_id = os.environ.get("ORCHESTRATOR_AGENT_ID", "")

    # Inject approval result as a new message
    approval_message = {
        "message_type": "approval_response",
        "approval_id": approval_id,
        "status": "approved",
        "decided_by": decided_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with foundry_span("post_message", thread_id=thread_id) as span:
        span.set_attribute("foundry.message_type", "approval_response")
        client.messages.create(
            thread_id=thread_id,
            role="user",
            content=json.dumps(approval_message),
        )

    # Create a new run to resume processing
    with agent_span("orchestrator", correlation_id=approval_id) as span:
        with foundry_span("create_run", thread_id=thread_id) as fspan:
            client.runs.create(
                thread_id=thread_id,
                agent_id=orchestrator_agent_id,
            )

    logger.info("Resumed Foundry thread %s after approval %s", thread_id, approval_id)
