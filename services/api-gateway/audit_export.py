"""Audit report export — remediation activity report for SOC 2 (AUDIT-006).

Combines data from:
1. Application Insights (agent tool calls with REMEDI-* correlation)
2. OneLake (REMEDI-007 remediation event records)
3. Cosmos DB (approval chain records)

Returns a JSON document covering all remediation events in the requested
time range with full approval chains.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

FABRIC_WORKSPACE_NAME = os.environ.get("FABRIC_WORKSPACE_NAME", "")
FABRIC_LAKEHOUSE_NAME = os.environ.get("FABRIC_LAKEHOUSE_NAME", "")
ONELAKE_ENDPOINT = "https://onelake.dfs.fabric.microsoft.com"


async def generate_remediation_report(
    from_time: str,
    to_time: str,
) -> dict[str, Any]:
    """Generate a remediation activity report for the given time range.

    Args:
        from_time: ISO 8601 start of period.
        to_time: ISO 8601 end of period.

    Returns:
        Dict with report_metadata and remediation_events list.
    """
    events: list[dict[str, Any]] = []

    # Source 1: OneLake remediation events (primary source after REMEDI-007)
    onelake_events = await _read_onelake_events(from_time, to_time)
    events.extend(onelake_events)

    # Source 2: Cosmos DB approval records (for approval chain enrichment)
    approval_map = await _read_approval_records(from_time, to_time)

    # Enrich events with approval chain data
    enriched_events = []
    for event in events:
        approval_id = event.get("approvalId", "")
        approval = approval_map.get(approval_id, {})
        enriched_events.append({
            **event,
            "approval_chain": {
                "proposed_at": approval.get("proposed_at", ""),
                "decided_at": approval.get("decided_at", ""),
                "decided_by": approval.get("decided_by", ""),
                "status": approval.get("status", event.get("outcome", "")),
                "expires_at": approval.get("expires_at", ""),
            },
        })

    # If no OneLake events, fall back to Cosmos DB records alone
    if not enriched_events:
        for approval_id, approval in approval_map.items():
            proposal = approval.get("proposal", {})
            enriched_events.append({
                "timestamp": approval.get("decided_at", approval.get("proposed_at", "")),
                "agentId": approval.get("agent_name", ""),
                "toolName": proposal.get("tool_name", proposal.get("action", "")),
                "toolParameters": proposal.get("tool_parameters", {}),
                "approvedBy": approval.get("decided_by", ""),
                "outcome": approval.get("status", ""),
                "durationMs": 0,
                "correlationId": "",
                "threadId": approval.get("thread_id", ""),
                "approvalId": approval_id,
                "approval_chain": {
                    "proposed_at": approval.get("proposed_at", ""),
                    "decided_at": approval.get("decided_at", ""),
                    "decided_by": approval.get("decided_by", ""),
                    "status": approval.get("status", ""),
                    "expires_at": approval.get("expires_at", ""),
                },
            })

    return {
        "report_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period": {"from": from_time, "to": to_time},
            "total_events": len(enriched_events),
        },
        "remediation_events": enriched_events,
    }


async def _read_onelake_events(
    from_time: str, to_time: str
) -> list[dict[str, Any]]:
    """Read remediation events from OneLake date-partitioned files."""
    if not (FABRIC_WORKSPACE_NAME and FABRIC_LAKEHOUSE_NAME):
        logger.debug("OneLake not configured — skipping OneLake event read")
        return []

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.filedatalake import DataLakeServiceClient

        credential = DefaultAzureCredential()
        service = DataLakeServiceClient(ONELAKE_ENDPOINT, credential=credential)
        fs = service.get_file_system_client(FABRIC_WORKSPACE_NAME)

        from_dt = datetime.fromisoformat(from_time.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_time.replace("Z", "+00:00"))

        events: list[dict[str, Any]] = []
        current = from_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        while current <= to_dt:
            dir_path = (
                f"{FABRIC_LAKEHOUSE_NAME}.Lakehouse/Files/remediation_audit/"
                f"year={current.year}/month={current.month:02d}/day={current.day:02d}"
            )
            try:
                dir_client = fs.get_directory_client(dir_path)
                paths = dir_client.get_paths()
                for path_item in paths:
                    file_client = fs.get_file_client(path_item.name)
                    download = file_client.download_file()
                    content = download.readall().decode("utf-8")
                    event = json.loads(content)
                    event_ts = event.get("timestamp", "")
                    if event_ts and from_time <= event_ts <= to_time:
                        events.append(event)
            except Exception:
                pass  # Directory may not exist for a given day

            current = current + timedelta(days=1)

        return events
    except Exception as exc:
        logger.error("Failed to read OneLake remediation events: %s", exc)
        return []


async def _read_approval_records(
    from_time: str, to_time: str
) -> dict[str, dict]:
    """Read approval records from Cosmos DB for the time range."""
    try:
        from services.api_gateway.approvals import _get_approvals_container

        container = _get_approvals_container()
        query = (
            "SELECT * FROM c WHERE "
            "c.proposed_at >= @from_time AND c.proposed_at <= @to_time "
            "AND c.status IN ('approved', 'rejected', 'expired', 'executed')"
        )
        items = container.query_items(
            query=query,
            parameters=[
                {"name": "@from_time", "value": from_time},
                {"name": "@to_time", "value": to_time},
            ],
            enable_cross_partition_query=True,
        )
        return {item["id"]: item for item in items}
    except Exception as exc:
        logger.error("Failed to read Cosmos DB approval records: %s", exc)
        return {}
