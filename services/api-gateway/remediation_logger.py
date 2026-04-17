from __future__ import annotations
"""Remediation audit logger — writes events to Fabric OneLake (REMEDI-007).

Every executed remediation action and every rejected/expired proposal
is recorded in OneLake with the full action log schema.

Write pattern: fire-and-forget async — never blocks the approval response.
Path: {lakehouse}.Lakehouse/Files/remediation_audit/year=YYYY/month=MM/day=DD/{event_id}.json
"""
import os

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

ONELAKE_ENDPOINT = "https://onelake.dfs.fabric.microsoft.com"
FABRIC_WORKSPACE_NAME = os.environ.get("FABRIC_WORKSPACE_NAME", "")
FABRIC_LAKEHOUSE_NAME = os.environ.get("FABRIC_LAKEHOUSE_NAME", "")


def _onelake_enabled() -> bool:
    """Check if OneLake configuration is available."""
    return bool(FABRIC_WORKSPACE_NAME and FABRIC_LAKEHOUSE_NAME)


async def log_remediation_event(event: dict[str, Any]) -> None:
    """Write a remediation event to OneLake lakehouse.

    Fire-and-forget: logs errors but never raises to caller.
    This prevents OneLake write failures from blocking the approval flow.

    Args:
        event: Dict with keys matching REMEDI-007 schema:
            - timestamp (ISO 8601)
            - agentId (str)
            - toolName (str)
            - toolParameters (dict)
            - approvedBy (str)
            - outcome (str: success|failure|rejected|expired)
            - durationMs (int)
            - correlationId (str)
            - threadId (str)
            - approvalId (str)
    """
    if not _onelake_enabled():
        logger.debug("OneLake not configured — skipping remediation event log")
        return

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.filedatalake import DataLakeServiceClient

        credential = DefaultAzureCredential()
        service = DataLakeServiceClient(ONELAKE_ENDPOINT, credential=credential)
        fs = service.get_file_system_client(FABRIC_WORKSPACE_NAME)

        now = datetime.now(timezone.utc)
        dir_path = (
            f"{FABRIC_LAKEHOUSE_NAME}.Lakehouse/Files/remediation_audit/"
            f"year={now.year}/month={now.month:02d}/day={now.day:02d}"
        )
        dir_client = fs.get_directory_client(dir_path)
        dir_client.create_directory()

        event_id = event.get("approvalId", "unknown")
        file_name = f"{event_id}_{now.strftime('%H%M%S')}.json"
        file_client = dir_client.create_file(file_name)

        data = json.dumps(event, default=str).encode("utf-8")
        file_client.append_data(data, offset=0, length=len(data))
        file_client.flush_data(len(data))

        logger.info(
            "Remediation event logged to OneLake: %s/%s (outcome=%s)",
            dir_path,
            file_name,
            event.get("outcome", "unknown"),
        )
    except Exception as exc:
        logger.error("Failed to log remediation event to OneLake: %s", exc)


def build_remediation_event(
    approval_record: dict[str, Any],
    outcome: str,
    duration_ms: int = 0,
    correlation_id: str = "",
) -> dict[str, Any]:
    """Build a REMEDI-007 compliant event from an approval record.

    Args:
        approval_record: Cosmos DB approval record dict.
        outcome: One of: success, failure, rejected, expired.
        duration_ms: Execution duration (0 for rejected/expired).
        correlation_id: Request correlation ID.

    Returns:
        Dict matching the REMEDI-007 schema.
    """
    proposal = approval_record.get("proposal", {})
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agentId": approval_record.get("agent_name", ""),
        "toolName": proposal.get("tool_name", proposal.get("action", "")),
        "toolParameters": proposal.get("tool_parameters", proposal.get("parameters", {})),
        "approvedBy": approval_record.get("decided_by", ""),
        "outcome": outcome,
        "durationMs": duration_ms,
        "correlationId": correlation_id,
        "threadId": approval_record.get("thread_id", ""),
        "approvalId": approval_record.get("id", ""),
    }
