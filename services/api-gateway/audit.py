"""Audit query endpoint — agent action history from Application Insights (AUDIT-004).

Queries OpenTelemetry spans exported to Application Insights via
Log Analytics KQL. Returns agent tool calls, handoffs, and approval
events for a given incident, filterable by agent, action type,
resource, and time range.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

APPINSIGHTS_CONNECTION_STRING = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
LOG_ANALYTICS_WORKSPACE_ID = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")


async def query_audit_log(
    incident_id: Optional[str] = None,
    agent: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query agent action history from Application Insights."""
    if not LOG_ANALYTICS_WORKSPACE_ID:
        logger.warning("LOG_ANALYTICS_WORKSPACE_ID not configured; returning empty audit log")
        return []

    # Build KQL query
    kql_parts = [
        "AppDependencies",
        "| where AppRoleName startswith 'agent-'",
    ]

    if incident_id:
        kql_parts.append(f"| where Properties has '{incident_id}'")
    if agent:
        kql_parts.append(f"| where AppRoleName == 'agent-{agent}'")
    if action:
        kql_parts.append(f"| where Name == '{action}'")
    if resource:
        kql_parts.append(f"| where Properties has '{resource}'")
    if from_time:
        kql_parts.append(f"| where TimeGenerated >= datetime('{from_time}')")
    if to_time:
        kql_parts.append(f"| where TimeGenerated <= datetime('{to_time}')")

    kql_parts.append(
        "| project TimeGenerated, AppRoleName, Name, ResultCode, DurationMs, Properties"
    )
    kql_parts.append("| order by TimeGenerated desc")
    kql_parts.append(f"| take {limit}")

    kql_query = "\n".join(kql_parts)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query import LogsQueryClient

        credential = DefaultAzureCredential()
        client = LogsQueryClient(credential)
        response = client.query_workspace(
            workspace_id=LOG_ANALYTICS_WORKSPACE_ID,
            query=kql_query,
            timespan=None,
        )

        results = []
        if response.tables:
            for row in response.tables[0].rows:
                results.append({
                    "timestamp": str(row[0]),
                    "agent": str(row[1]).replace("agent-", ""),
                    "tool": str(row[2]),
                    "outcome": str(row[3]),
                    "duration_ms": float(row[4]) if row[4] else 0,
                    "properties": str(row[5]),
                })
        return results
    except Exception as exc:
        logger.error("Audit query failed: %s", exc)
        return []
