"""Approval Manager — thread parking and resume logic (REMEDI-002, D-10).

Implements the write-then-return pattern:
1. Agent writes approval record to Cosmos DB with status: pending
2. Agent posts Adaptive Card to Teams (non-blocking)
3. Agent returns from its current turn (thread is idle, not blocked)
4. Webhook callback resumes the thread via message + new run
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:
    from azure.cosmos import ContainerProxy, CosmosClient
except ImportError:
    ContainerProxy = None  # type: ignore[assignment,misc]
    CosmosClient = None  # type: ignore[assignment,misc]

try:
    from azure.identity import DefaultAzureCredential
except ImportError:
    DefaultAzureCredential = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_MINUTES = int(os.environ.get("APPROVAL_TIMEOUT_MINUTES", "30"))


def create_approval_record(
    container: Optional[ContainerProxy],
    thread_id: str,
    incident_id: str,
    agent_name: str,
    proposal: dict,
    resource_snapshot: dict,
    risk_level: str,
) -> dict:
    """Create a pending approval record in Cosmos DB.

    Implements the write-then-return pattern: agent writes the record
    and returns. The webhook callback (approve/reject endpoint) resumes
    the thread via a new Foundry run.
    """
    if container is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        if CosmosClient is None or DefaultAzureCredential is None:
            raise ImportError("azure-cosmos and azure-identity are required.")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
        database = cosmos_client.get_database_client(database_name)
        container = database.get_container_client("approvals")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=APPROVAL_TIMEOUT_MINUTES)

    record = {
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

    return container.create_item(body=record)
