from __future__ import annotations
"""Change Correlation Engine — correlates incidents with recent Azure resource changes.

Runs as a FastAPI BackgroundTask after POST /api/v1/incidents. Queries the Azure
Activity Log for the incident's primary resource and all topology neighbors within
blast_radius, then scores each change event by temporal proximity, topological
distance, and change type. Stores the top-3 ChangeCorrelation objects on the
incident document in Cosmos DB (field: top_changes).

Satisfies INTEL-002: change correlation surfaces correct cause within 30 seconds
of incident creation.

All steps run with individual error handling. Correlator never raises — all
failures are logged. Partial results are better than no results.
"""
import os

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.api_gateway.models import ChangeCorrelation

logger = logging.getLogger(__name__)

# Configuration from environment
CORRELATOR_ENABLED: bool = os.environ.get("CHANGE_CORRELATOR_ENABLED", "true").lower() == "true"
CORRELATOR_TIMEOUT: int = int(os.environ.get("CHANGE_CORRELATOR_TIMEOUT_SECONDS", "25"))
CORRELATOR_WINDOW_MINUTES: int = int(os.environ.get("CORRELATOR_WINDOW_MINUTES", "30"))
CORRELATOR_MAX_RESULTS: int = int(os.environ.get("CORRELATOR_MAX_RESULTS", "3"))

# Scoring weights (must sum to 1.0)
W_TEMPORAL: float = 0.5
W_TOPOLOGY: float = 0.3
W_CHANGE_TYPE: float = 0.2

# Change-type score table (operation_name prefix → score)
_CHANGE_TYPE_SCORES: dict[str, float] = {
    "microsoft.compute/virtualmachines/write": 0.9,
    "microsoft.sql/servers/databases/write": 0.8,
    "microsoft.network/networksecuritygroups/write": 0.8,
    "microsoft.resources/deployments/write": 0.7,
    "microsoft.authorization/roleassignments/write": 0.6,
}
_CHANGE_TYPE_DEFAULT: float = 0.4


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from ARM resource ID.

    Identical logic to diagnostic_pipeline._extract_subscription_id — duplicated to
    avoid a cross-module dependency on a private helper.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return resource_id.split("/")[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot extract subscription_id from resource_id: {resource_id}")


def _resource_name(resource_id: str) -> str:
    """Return the last non-empty path segment of an ARM resource ID."""
    parts = [p for p in resource_id.split("/") if p]
    return parts[-1] if parts else resource_id


def _change_type_score(operation_name: str) -> float:
    """Look up a change-type score for the given ARM operation name.

    Matches on normalized (lowercase) operation_name prefix.
    Returns _CHANGE_TYPE_DEFAULT for unknown operations.
    """
    normalized = (operation_name or "").lower()
    for prefix, score in _CHANGE_TYPE_SCORES.items():
        if normalized.startswith(prefix):
            return score
    return _CHANGE_TYPE_DEFAULT


def _score_event(
    delta_minutes: float,
    topology_distance: int,
    operation_name: str,
    window_minutes: int,
) -> tuple[float, float]:
    """Compute (change_type_score, correlation_score) for one Activity Log event.

    Scoring formula:
        temporal_score    = 1.0 - (delta_minutes / window_minutes)   # clamp [0, 1]
        topology_score    = 1.0 / (topology_distance + 1)            # 1.0, 0.5, 0.33, ...
        change_type_score = _change_type_score(operation_name)

        correlation_score = W_TEMPORAL * temporal_score
                          + W_TOPOLOGY * topology_score
                          + W_CHANGE_TYPE * change_type_score
    """
    temporal_score = max(0.0, min(1.0, 1.0 - (delta_minutes / window_minutes)))
    topology_score = 1.0 / (topology_distance + 1)
    ct_score = _change_type_score(operation_name)
    correlation = W_TEMPORAL * temporal_score + W_TOPOLOGY * topology_score + W_CHANGE_TYPE * ct_score
    return ct_score, round(correlation, 4)


async def _query_activity_log_for_resource(
    credential: Any,
    resource_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Query Activity Log for write/action events on one resource in the given window.

    Returns a list of raw event dicts with keys:
        event_id, operation_name, caller, status, event_timestamp
    Returns [] on any error (logged but not raised).
    """
    try:
        from azure.mgmt.monitor import MonitorManagementClient

        sub_id = _extract_subscription_id(resource_id)
        filter_str = (
            f"eventTimestamp ge '{window_start.isoformat()}' "
            f"and eventTimestamp le '{window_end.isoformat()}' "
            f"and resourceId eq '{resource_id}'"
        )
        client = MonitorManagementClient(credential, sub_id)
        events = await asyncio.get_event_loop().run_in_executor(
            None, lambda: list(client.activity_logs.list(filter=filter_str))
        )
        results = []
        for event in events:
            op = event.operation_name.value if event.operation_name else ""
            # Only correlate write/action operations — skip reads and diagnostics
            if not (op.lower().endswith("/write") or op.lower().endswith("/action")):
                continue
            results.append({
                "event_id": getattr(event, "event_data_id", None) or getattr(event, "correlation_id", None) or "",
                "operation_name": op,
                "caller": event.caller,
                "status": event.status.value if event.status else "Unknown",
                "event_timestamp": event.event_timestamp,
            })
        logger.debug(
            "correlator: activity_log query | resource=%s events=%d write_events=%d",
            resource_id[:80], len(events), len(results),
        )
        return results
    except Exception as exc:
        logger.warning(
            "correlator: activity_log query failed | resource=%s error=%s",
            resource_id[:80], exc,
        )
        return []


async def correlate_incident_changes(
    incident_id: str,
    resource_id: str,
    incident_created_at: datetime,
    credential: Any,
    cosmos_client: Any,
    topology_client: Optional[Any] = None,
    window_minutes: int = CORRELATOR_WINDOW_MINUTES,
    max_correlations: int = CORRELATOR_MAX_RESULTS,
    cosmos_db_name: str = "aap",
) -> None:
    """Correlate an incident with recent Azure resource changes.

    Called as a BackgroundTask from ingest_incident. Queries the Activity Log
    for the incident's primary resource and all topology neighbors, scores each
    change event, and writes the top-N results to the incident document in Cosmos.

    Args:
        incident_id: Unique incident identifier (Cosmos document ID).
        resource_id: Primary affected resource ARM ID.
        incident_created_at: UTC datetime when the incident was created.
        credential: Azure DefaultAzureCredential instance.
        cosmos_client: CosmosClient instance (may be None in dev/test mode).
        topology_client: Optional TopologyClient for blast-radius expansion.
        window_minutes: How far back to look for changes (default: CORRELATOR_WINDOW_MINUTES).
        max_correlations: Maximum ChangeCorrelation objects to store (default: CORRELATOR_MAX_RESULTS).
        cosmos_db_name: Cosmos DB database name.
    """
    if not CORRELATOR_ENABLED:
        logger.info("correlator: disabled | incident_id=%s", incident_id)
        return

    try:
        correlator_start = time.monotonic()
        logger.info(
            "correlator: starting | incident_id=%s resource_id=%s window_minutes=%d",
            incident_id, resource_id, window_minutes,
        )

        window_start = incident_created_at - timedelta(minutes=window_minutes)

        # Step 1: Build list of resources to query — start with the primary resource
        resources_to_query: list[tuple[str, int]] = [(resource_id, 0)]

        if topology_client is not None:
            try:
                blast = await asyncio.get_event_loop().run_in_executor(
                    None, topology_client.get_blast_radius, resource_id, 3
                )
                for entry in blast.get("affected_resources", []):
                    resources_to_query.append((entry["resource_id"], entry["hop_count"]))
                logger.debug(
                    "correlator: topology expanded | incident_id=%s total_resources=%d",
                    incident_id, len(resources_to_query),
                )
            except Exception as topo_exc:
                logger.warning(
                    "correlator: topology expansion failed | incident_id=%s error=%s",
                    incident_id, topo_exc,
                )

        # Step 2: Query Activity Log for all resources in parallel
        query_tasks = [
            asyncio.create_task(
                asyncio.wait_for(
                    _query_activity_log_for_resource(credential, rid, window_start, incident_created_at),
                    timeout=CORRELATOR_TIMEOUT,
                )
            )
            for rid, _ in resources_to_query
        ]
        query_results = await asyncio.gather(*query_tasks, return_exceptions=True)

        # Step 3: Score all events and build candidates
        candidates: list[ChangeCorrelation] = []
        for (rid, distance), result in zip(resources_to_query, query_results):
            if isinstance(result, Exception):
                logger.warning(
                    "correlator: query task failed | resource=%s error=%s",
                    rid[:80], result,
                )
                continue
            for event in result:
                ts = event["event_timestamp"]
                if ts is None:
                    continue
                # Ensure timezone-aware for subtraction
                if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                delta_minutes = (incident_created_at - ts).total_seconds() / 60
                # Skip events outside the correlation window
                if delta_minutes < 0 or delta_minutes > window_minutes:
                    continue
                op = event["operation_name"]
                ct_score, score = _score_event(delta_minutes, distance, op, window_minutes)
                change_id = event.get("event_id") or f"{rid}:{op}:{ts.isoformat()}"
                candidates.append(
                    ChangeCorrelation(
                        change_id=change_id,
                        operation_name=op,
                        resource_id=rid,
                        resource_name=_resource_name(rid),
                        caller=event.get("caller"),
                        changed_at=ts.isoformat(),
                        delta_minutes=round(delta_minutes, 2),
                        topology_distance=distance,
                        change_type_score=ct_score,
                        correlation_score=score,
                        status=event.get("status", "Unknown"),
                    )
                )

        # Step 4: Sort and take top-N
        candidates.sort(key=lambda c: c.correlation_score, reverse=True)
        top = candidates[:max_correlations]

        top_score = top[0].correlation_score if top else 0.0
        logger.info(
            "correlator: scored | incident_id=%s candidates=%d top_score=%.2f",
            incident_id, len(candidates), top_score,
        )

        # Step 5: Persist to Cosmos DB
        if cosmos_client is None:
            logger.warning(
                "correlator: cosmos_client=None | correlations not persisted | incident_id=%s",
                incident_id,
            )
            return

        try:
            db = cosmos_client.get_database_client(cosmos_db_name)
            container = db.get_container_client("incidents")
            incident_doc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: container.read_item(incident_id, partition_key=incident_id),
            )
            incident_doc["top_changes"] = [c.model_dump() for c in top]
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: container.replace_item(incident_id, incident_doc),
            )
            logger.info(
                "correlator: top_changes written | incident_id=%s count=%d",
                incident_id, len(top),
            )
        except Exception as cosmos_exc:
            logger.error(
                "correlator: cosmos_write failed | incident_id=%s error=%s",
                incident_id, cosmos_exc, exc_info=True,
            )

        total_duration_ms = (time.monotonic() - correlator_start) * 1000
        logger.info(
            "correlator: complete | incident_id=%s duration_ms=%.0f",
            incident_id, total_duration_ms,
        )

    except Exception as exc:
        logger.error(
            "correlator: fatal_error | incident_id=%s error=%s",
            incident_id, exc, exc_info=True,
        )
    # Never raise — correlator runs in background
