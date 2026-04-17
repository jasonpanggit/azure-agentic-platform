from __future__ import annotations
"""Alert Correlation Timeline endpoints — Phase 72.

Exposes the change-correlation and noise-reduction story for a single incident
so that operators can understand why alerts were collapsed and which Azure
resource changes caused them.

All handlers follow the no-raise convention: structured error dicts are
returned instead of raising exceptions.
"""
import os

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_optional_cosmos_client

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE_ID", "aap-db")
COSMOS_INCIDENTS_CONTAINER: str = os.environ.get("COSMOS_CONTAINER_ID", "incidents")

# Weights must match change_correlator.py
W_TEMPORAL: float = 0.5
W_TOPOLOGY: float = 0.3
W_CHANGE_TYPE: float = 0.2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_reason_chips(change: dict[str, Any]) -> list[str]:
    """Derive human-readable reason chips from score breakdown.

    Reads individual score fields stored on the ChangeCorrelation dict and
    maps them to short labels shown as badges in the UI.
    """
    chips: list[str] = []

    # Temporal chip — derive minutes from delta_minutes stored by correlator
    temporal_score = _temporal_score_from_delta(change.get("delta_minutes", 999))
    if temporal_score > 0.7:
        delta = change.get("delta_minutes", 0)
        label = f"{int(round(delta))} min before" if delta >= 1 else "< 1 min before"
        chips.append(f"Temporal ({label})")

    # Topology chip
    topo_distance = change.get("topology_distance", 99)
    if topo_distance == 0:
        chips.append("Same resource")
    elif topo_distance == 1:
        chips.append("Topology neighbor")

    # Change-type chip — derive from operation_name
    op = (change.get("operation_name") or "").lower()
    change_type_score = change.get("change_type_score", 0.0)
    if change_type_score > 0.7:
        if "write" in op:
            chips.append("Write operation")
        elif "delete" in op:
            chips.append("Delete operation")
        else:
            chips.append("High-impact operation")

    # Caller chip — include if a human caller is present
    caller = change.get("caller")
    if caller and "@" in caller:
        chips.append(f"By {caller}")

    return chips if chips else ["Correlated"]


def _temporal_score_from_delta(delta_minutes: float) -> float:
    """Replicate the correlator's temporal scoring formula for chip generation.

    Mirrors change_correlator._temporal_score: score decays from 1.0 at 0 min
    to 0.0 at 60 min, clamped to [0, 1].
    """
    if delta_minutes <= 0:
        return 0.0
    score = max(0.0, 1.0 - (delta_minutes / 60.0))
    return score


def _score_breakdown(change: dict[str, Any]) -> dict[str, float]:
    """Build the score_breakdown sub-object from raw correlation fields."""
    delta = change.get("delta_minutes", 999)
    temporal = _temporal_score_from_delta(delta)
    topo_distance = change.get("topology_distance", 99)
    topology = max(0.0, 1.0 - topo_distance * 0.3) if topo_distance >= 0 else 0.0
    change_type = change.get("change_type_score", 0.0)
    weighted = W_TEMPORAL * temporal + W_TOPOLOGY * topology + W_CHANGE_TYPE * change_type
    return {
        "temporal_score": round(temporal, 4),
        "topology_score": round(topology, 4),
        "change_type_score": round(change_type, 4),
        "weighted_total": round(weighted, 4),
    }


def _build_correlation_summary(changes: list[dict[str, Any]], window_minutes: int) -> str:
    count = len(changes)
    if count == 0:
        return "No correlated changes found"
    noun = "change event" if count == 1 else "change events"
    return f"{count} related {noun} found within {window_minutes}-minute window"


def _composite_severity_reason(incident: dict[str, Any]) -> Optional[str]:
    """Generate a human-readable explanation for composite severity escalation."""
    blast = incident.get("blast_radius")
    composite = incident.get("composite_severity")
    original = incident.get("severity")
    if not composite or composite == original:
        return None
    if blast:
        return f"Blast radius {blast} → {composite}"
    return f"Noise reduction elevated severity to {composite}"


def _fetch_incident(cosmos_client: Any, incident_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single incident document by incident_id (cross-partition query)."""
    try:
        db = cosmos_client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(COSMOS_INCIDENTS_CONTAINER)
        query = "SELECT * FROM c WHERE c.incident_id = @id"
        params: list[dict[str, Any]] = [{"name": "@id", "value": incident_id}]
        items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items[0] if items else None
    except Exception as exc:  # noqa: BLE001
        logger.error("cosmos fetch failed for incident %s: %s", incident_id, exc)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}/alert-timeline",
    summary="Alert Correlation Timeline",
    tags=["incidents"],
)
def get_alert_timeline(
    incident_id: str,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Return the full correlation story for a single incident.

    Reads top_changes, composite_severity, suppressed, blast_radius from the
    Cosmos incident doc and assembles a response suitable for the frontend
    AlertTimeline component.
    """
    start = time.monotonic()

    if cosmos_client is None:
        logger.warning("alert_timeline: cosmos unavailable")
        return JSONResponse(
            status_code=503,
            content={
                "error": "Cosmos DB unavailable — correlation data cannot be retrieved",
                "incident_id": incident_id,
            },
        )

    incident = _fetch_incident(cosmos_client, incident_id)
    if incident is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Incident {incident_id!r} not found", "incident_id": incident_id},
        )

    raw_changes: list[dict[str, Any]] = incident.get("top_changes") or []
    window_minutes: int = int(os.environ.get("CORRELATOR_WINDOW_MINUTES", "30"))

    # Build enriched change list
    change_correlations: list[dict[str, Any]] = []
    for ch in raw_changes:
        score_breakdown = _score_breakdown(ch)
        chips = _build_reason_chips(ch)
        change_correlations.append(
            {
                "operation_name": ch.get("operation_name", ""),
                "resource_id": ch.get("resource_id", ""),
                "resource_name": ch.get("resource_name", ""),
                "caller": ch.get("caller"),
                "timestamp": ch.get("changed_at"),
                "correlation_score": round(ch.get("correlation_score", 0.0), 4),
                "score_breakdown": score_breakdown,
                "reason_chips": chips,
            }
        )

    # Sort by correlation_score descending
    change_correlations.sort(key=lambda x: x["correlation_score"], reverse=True)

    suppressed: bool = bool(incident.get("suppressed", False))
    parent_id: Optional[str] = incident.get("suppressed_by") or incident.get("parent_incident_id")
    blast_radius: Optional[int] = incident.get("blast_radius")
    composite_severity: Optional[str] = incident.get("composite_severity")

    noise_reduction: dict[str, Any] = {
        "suppression_reason": incident.get("suppression_reason") if suppressed else None,
        "composite_severity_reason": _composite_severity_reason(incident),
        "correlation_window_minutes": window_minutes,
    }

    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        "alert_timeline: incident=%s changes=%d suppressed=%s duration_ms=%.1f",
        incident_id,
        len(change_correlations),
        suppressed,
        duration_ms,
    )

    return JSONResponse(
        content={
            "incident_id": incident_id,
            "title": incident.get("title") or incident.get("description", ""),
            "severity": incident.get("severity"),
            "composite_severity": composite_severity,
            "detected_at": incident.get("created_at") or incident.get("detected_at"),
            "suppressed": suppressed,
            "parent_incident_id": parent_id,
            "blast_radius": blast_radius,
            "correlation_summary": _build_correlation_summary(change_correlations, window_minutes),
            "change_correlations": change_correlations,
            "noise_reduction": noise_reduction,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.get(
    "/api/v1/incidents/{incident_id}/correlation-summary",
    summary="Lightweight Correlation Summary",
    tags=["incidents"],
)
def get_correlation_summary(
    incident_id: str,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> JSONResponse:
    """Lightweight summary suitable for the incident list view.

    Returns has_correlations, correlation_count, top_change label, blast_radius.
    """
    start = time.monotonic()

    if cosmos_client is None:
        logger.warning("correlation_summary: cosmos unavailable for %s", incident_id)
        return JSONResponse(
            status_code=503,
            content={
                "error": "Cosmos DB unavailable",
                "incident_id": incident_id,
            },
        )

    incident = _fetch_incident(cosmos_client, incident_id)
    if incident is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Incident {incident_id!r} not found", "incident_id": incident_id},
        )

    raw_changes: list[dict[str, Any]] = incident.get("top_changes") or []
    top_change_label: Optional[str] = None
    if raw_changes:
        top = raw_changes[0]
        rname = top.get("resource_name", "")
        op = top.get("operation_name", "")
        op_suffix = op.split("/")[-1] if "/" in op else op
        top_change_label = f"{rname} {op_suffix}" if rname else op_suffix

    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info("correlation_summary: incident=%s count=%d duration_ms=%.1f", incident_id, len(raw_changes), duration_ms)

    return JSONResponse(
        content={
            "incident_id": incident_id,
            "has_correlations": len(raw_changes) > 0,
            "correlation_count": len(raw_changes),
            "top_change": top_change_label,
            "blast_radius": incident.get("blast_radius"),
        }
    )
