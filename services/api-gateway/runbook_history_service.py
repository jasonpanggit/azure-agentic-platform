from __future__ import annotations
"""Runbook execution history service — reads from remediation_audit Cosmos container.

Never raises; all errors are logged and empty/default results are returned.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COSMOS_REMEDIATION_AUDIT_CONTAINER = "remediation_audit"
_SUCCESS_STATUSES = {"RESOLVED", "IMPROVED"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RunbookExecution:
    execution_id: str
    incident_id: str
    action_name: str
    action_class: str       # SAFE / CAUTIOUS / DESTRUCTIVE
    resource_id: str
    resource_name: str      # extracted from resource_id
    resource_group: str
    subscription_id: str
    status: str             # RESOLVED / IMPROVED / DEGRADED / TIMEOUT / BLOCKED
    executed_at: str
    duration_ms: int
    approved_by: str
    rollback_available: bool
    pre_check_passed: bool
    success: bool           # status in (RESOLVED, IMPROVED)
    notes: str


@dataclass
class RunbookStats:
    total_executions: int
    success_rate: float                  # 0.0–1.0
    avg_duration_ms: float
    by_action: Dict[str, Any]            # {action_name: {count, success_rate}}
    by_status: Dict[str, int]            # {status: count}
    by_action_class: Dict[str, int]      # {SAFE/CAUTIOUS/DESTRUCTIVE: count}
    top_resources: List[Dict[str, Any]]  # [{resource_name, execution_count}]
    recent_failures: List[RunbookExecution]  # last 5 DEGRADED/TIMEOUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_resource_name(resource_id: str) -> str:
    """Return the last segment of an Azure resource ID."""
    if not resource_id:
        return ""
    return resource_id.rstrip("/").split("/")[-1]


def _record_to_execution(doc: Dict[str, Any]) -> RunbookExecution:
    status = doc.get("status", "")
    resource_id = doc.get("resource_id", "")
    return RunbookExecution(
        execution_id=doc.get("id", ""),
        incident_id=doc.get("incident_id", ""),
        action_name=doc.get("action_name", ""),
        action_class=doc.get("action_class", "SAFE"),
        resource_id=resource_id,
        resource_name=_extract_resource_name(resource_id),
        resource_group=doc.get("resource_group", ""),
        subscription_id=doc.get("subscription_id", ""),
        status=status,
        executed_at=doc.get("executed_at", ""),
        duration_ms=int(doc.get("duration_ms", 0)),
        approved_by=doc.get("approved_by", ""),
        rollback_available=bool(doc.get("rollback_available", False)),
        pre_check_passed=bool(doc.get("pre_check_passed", True)),
        success=status in _SUCCESS_STATUSES,
        notes=doc.get("notes", ""),
    )


def _get_container(cosmos_client: Any, db_name: str) -> Any:
    return (
        cosmos_client
        .get_database_client(db_name)
        .get_container_client(COSMOS_REMEDIATION_AUDIT_CONTAINER)
    )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def get_execution_history(
    cosmos_client: Any,
    db_name: str,
    subscription_ids: Optional[List[str]] = None,
    action_class: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[RunbookExecution]:
    """Return execution history from remediation_audit, newest first.

    Never raises — returns [] on any error.
    """
    start = time.monotonic()
    try:
        container = _get_container(cosmos_client, db_name)
        conditions: List[str] = []
        params: List[Dict[str, Any]] = []

        if subscription_ids:
            placeholders = ", ".join(f"@sub{i}" for i in range(len(subscription_ids)))
            conditions.append(f"c.subscription_id IN ({placeholders})")
            for i, sid in enumerate(subscription_ids):
                params.append({"name": f"@sub{i}", "value": sid})

        if action_class:
            conditions.append("c.action_class = @action_class")
            params.append({"name": "@action_class", "value": action_class})

        if status:
            conditions.append("c.status = @status")
            params.append({"name": "@status", "value": status})

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = (
            f"SELECT TOP {limit} * FROM c {where_clause} "
            f"ORDER BY c.executed_at DESC"
        )

        items = list(container.query_items(
            query=query,
            parameters=params if params else None,
            enable_cross_partition_query=True,
        ))

        executions = [_record_to_execution(doc) for doc in items]
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "get_execution_history returned %d records in %.1f ms",
            len(executions), duration_ms,
        )
        return executions
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "get_execution_history failed after %.1f ms: %s", duration_ms, exc
        )
        return []


def get_runbook_stats(
    cosmos_client: Any,
    db_name: str,
    days: int = 7,
) -> RunbookStats:
    """Aggregate stats for the last N days. Never raises."""
    start = time.monotonic()
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        container = _get_container(cosmos_client, db_name)
        query = (
            "SELECT * FROM c WHERE c.executed_at >= @cutoff "
            "ORDER BY c.executed_at DESC"
        )
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@cutoff", "value": cutoff}],
            enable_cross_partition_query=True,
        ))

        executions = [_record_to_execution(doc) for doc in items]
        total = len(executions)

        if total == 0:
            return RunbookStats(
                total_executions=0,
                success_rate=0.0,
                avg_duration_ms=0.0,
                by_action={},
                by_status={},
                by_action_class={},
                top_resources=[],
                recent_failures=[],
            )

        successes = sum(1 for e in executions if e.success)
        success_rate = successes / total
        avg_duration = sum(e.duration_ms for e in executions) / total

        # by_action
        action_counts: Dict[str, Dict[str, Any]] = {}
        for e in executions:
            if e.action_name not in action_counts:
                action_counts[e.action_name] = {"count": 0, "successes": 0}
            action_counts[e.action_name]["count"] += 1
            if e.success:
                action_counts[e.action_name]["successes"] += 1
        by_action = {
            name: {
                "count": v["count"],
                "success_rate": v["successes"] / v["count"] if v["count"] else 0.0,
            }
            for name, v in action_counts.items()
        }

        # by_status
        by_status: Dict[str, int] = {}
        for e in executions:
            by_status[e.status] = by_status.get(e.status, 0) + 1

        # by_action_class
        by_action_class: Dict[str, int] = {}
        for e in executions:
            by_action_class[e.action_class] = by_action_class.get(e.action_class, 0) + 1

        # top_resources
        resource_counts: Dict[str, int] = {}
        for e in executions:
            resource_counts[e.resource_name] = resource_counts.get(e.resource_name, 0) + 1
        top_resources = [
            {"resource_name": name, "execution_count": count}
            for name, count in sorted(
                resource_counts.items(), key=lambda x: x[1], reverse=True
            )[:10]
        ]

        # recent_failures (DEGRADED or TIMEOUT)
        failures = [e for e in executions if e.status in ("DEGRADED", "TIMEOUT")]
        recent_failures = failures[:5]

        duration_ms = (time.monotonic() - start) * 1000
        logger.info("get_runbook_stats computed in %.1f ms (total=%d)", duration_ms, total)

        return RunbookStats(
            total_executions=total,
            success_rate=success_rate,
            avg_duration_ms=avg_duration,
            by_action=by_action,
            by_status=by_status,
            by_action_class=by_action_class,
            top_resources=top_resources,
            recent_failures=recent_failures,
        )
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error("get_runbook_stats failed after %.1f ms: %s", duration_ms, exc)
        return RunbookStats(
            total_executions=0,
            success_rate=0.0,
            avg_duration_ms=0.0,
            by_action={},
            by_status={},
            by_action_class={},
            top_resources=[],
            recent_failures=[],
        )


def get_execution_by_incident(
    cosmos_client: Any,
    db_name: str,
    incident_id: str,
) -> List[RunbookExecution]:
    """Return all executions for a specific incident. Never raises."""
    start = time.monotonic()
    try:
        container = _get_container(cosmos_client, db_name)
        query = (
            "SELECT * FROM c WHERE c.incident_id = @incident_id "
            "ORDER BY c.executed_at DESC"
        )
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@incident_id", "value": incident_id}],
            enable_cross_partition_query=True,
        ))
        executions = [_record_to_execution(doc) for doc in items]
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "get_execution_by_incident(%s) returned %d records in %.1f ms",
            incident_id, len(executions), duration_ms,
        )
        return executions
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "get_execution_by_incident failed after %.1f ms: %s", duration_ms, exc
        )
        return []
