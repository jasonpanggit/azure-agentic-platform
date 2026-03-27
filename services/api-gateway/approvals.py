"""Approval endpoints — HITL gate for remediation proposals (REMEDI-002, REMEDI-003, REMEDI-005).

Handles approval lifecycle: read, approve, reject with ETag concurrency.
Expired proposals return 410 Gone. Thread resume on approval callback.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from azure.cosmos import ContainerProxy, CosmosClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_MINUTES = int(os.environ.get("APPROVAL_TIMEOUT_MINUTES", "30"))


def _get_approvals_container() -> ContainerProxy:
    """Get the Cosmos DB approvals container."""
    endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if not endpoint:
        raise ValueError("COSMOS_ENDPOINT environment variable is required.")
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    credential = DefaultAzureCredential()
    client = CosmosClient(url=endpoint, credential=credential)
    database = client.get_database_client(database_name)
    return database.get_container_client("approvals")


def _is_expired(record: dict) -> bool:
    """Check if an approval record has expired."""
    expires_at = datetime.fromisoformat(record["expires_at"])
    return datetime.now(timezone.utc) > expires_at


async def get_approval(approval_id: str, thread_id: str) -> dict:
    """Read an approval record from Cosmos DB."""
    container = _get_approvals_container()
    return container.read_item(item=approval_id, partition_key=thread_id)


async def list_approvals_for_thread(thread_id: str) -> list[dict]:
    """List all approval records for a thread."""
    container = _get_approvals_container()
    query = "SELECT * FROM c WHERE c.thread_id = @thread_id"
    items = container.query_items(
        query=query,
        parameters=[{"name": "@thread_id", "value": thread_id}],
        partition_key=thread_id,
    )
    return list(items)


async def list_approvals_by_status(status_filter: str = "pending") -> list[dict]:
    """List all approval records matching the given status (TEAMS-005).

    Cross-partition query -- acceptable for small pending approval counts.
    Used by the Teams bot escalation scheduler.
    """
    container = _get_approvals_container()
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
) -> dict:
    """Process an approve/reject decision on a pending proposal.

    Enforces:
    - ETag optimistic concurrency (REMEDI-003)
    - 30-minute expiry — returns 410 Gone for expired (D-13)
    - Only "pending" records can be decided
    """
    container = _get_approvals_container()
    record = container.read_item(item=approval_id, partition_key=thread_id)
    etag = record["_etag"]

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

    result = container.replace_item(
        item=approval_id,
        body=updated_record,
        etag=etag,
        match_condition="IfMatch",
    )

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

    client.agents.create_message(
        thread_id=thread_id,
        role="user",
        content=json.dumps(approval_message),
    )

    # Create a new run to resume processing
    client.agents.create_run(
        thread_id=thread_id,
        assistant_id=orchestrator_agent_id,
    )

    logger.info("Resumed Foundry thread %s after approval %s", thread_id, approval_id)
