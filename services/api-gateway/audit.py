"""Audit query endpoint — agent action history from Application Insights (AUDIT-004).

Queries OpenTelemetry spans exported to Application Insights via
Log Analytics KQL. Returns agent tool calls, handoffs, and approval
events for a given incident, filterable by agent, action type,
resource, and time range.
"""
from __future__ import annotations

from datetime import datetime
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

APPINSIGHTS_CONNECTION_STRING = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
LOG_ANALYTICS_WORKSPACE_ID = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")

_SAFE_AGENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SAFE_ACTION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,256}$")
_MAX_AUDIT_LIMIT = 200


def _validate_agent(agent: Optional[str]) -> Optional[str]:
    if agent is None:
        return None
    if not _SAFE_AGENT_PATTERN.fullmatch(agent):
        raise ValueError("Invalid agent filter. Use lowercase agent names like 'compute'.")
    return agent


def _validate_action(action: Optional[str]) -> Optional[str]:
    if action is None:
        return None
    if not _SAFE_ACTION_PATTERN.fullmatch(action):
        raise ValueError("Invalid action filter. Use action names without quotes or operators.")
    return action


def _validate_token_filter(filter_name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not _SAFE_TOKEN_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {filter_name} filter. Use resource IDs or IDs without quotes.")
    return value


def _validate_iso8601(filter_name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {filter_name}. Expected ISO 8601 datetime.") from exc
    return value


def _validate_limit(limit: int) -> int:
    if not isinstance(limit, int):
        raise ValueError("Invalid limit. Expected an integer.")
    if limit < 1 or limit > _MAX_AUDIT_LIMIT:
        raise ValueError(f"Invalid limit. Use a value between 1 and {_MAX_AUDIT_LIMIT}.")
    return limit


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
    incident_id = _validate_token_filter("incident_id", incident_id)
    agent = _validate_agent(agent)
    action = _validate_action(action)
    resource = _validate_token_filter("resource", resource)
    from_time = _validate_iso8601("from_time", from_time)
    to_time = _validate_iso8601("to_time", to_time)
    limit = _validate_limit(limit)

    if not LOG_ANALYTICS_WORKSPACE_ID:
        logger.warning("LOG_ANALYTICS_WORKSPACE_ID not configured; returning empty audit log")
        return []

    # Build KQL query
    kql_parts = [
        "AppDependencies",
        "| where AppRoleName startswith 'agent-'",
    ]

    # SECURITY: every interpolated value below is validated before reaching
    # this block. Azure Monitor Query does not support parameterized KQL.

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
