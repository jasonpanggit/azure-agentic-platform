"""Noise reducer service for alert intelligence (INTEL-001).

Implements three noise reduction mechanisms:
- Causal suppression: suppress downstream cascade alerts
- Temporal/topological correlation: route new alerts to existing incident threads
- Composite severity scoring: re-weight severity with blast radius and domain SLO risk
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time as _time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (env-driven)
# ---------------------------------------------------------------------------

SUPPRESSION_ENABLED: bool = os.environ.get("NOISE_SUPPRESSION_ENABLED", "true").lower() == "true"
SUPPRESSION_LOOKBACK_HOURS: int = int(os.environ.get("NOISE_SUPPRESSION_LOOKBACK_HOURS", "2"))
CORRELATION_WINDOW_MINUTES: int = int(os.environ.get("NOISE_CORRELATION_WINDOW_MINUTES", "10"))

COSMOS_DB_NAME: str = os.environ.get("COSMOS_DB_NAME", "aap")

# ---------------------------------------------------------------------------
# Domain SLO risk weights
# ---------------------------------------------------------------------------

_DOMAIN_SLO_RISK: dict[str, float] = {
    "compute": 0.9,
    "network": 0.85,
    "storage": 0.8,
    "database": 0.8,
    "security": 1.0,
    "sre": 0.7,
    "arc": 0.6,
    "patch": 0.4,
}
_DOMAIN_SLO_RISK_DEFAULT: float = 0.5

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _base_severity_weight(severity: str) -> float:
    """Return a numeric weight for a severity string.

    Sev0 → 1.0, Sev1 → 0.8, Sev2 → 0.6, Sev3 → 0.4, unknown → 0.4
    """
    _MAP: dict[str, float] = {
        "Sev0": 1.0,
        "Sev1": 0.8,
        "Sev2": 0.6,
        "Sev3": 0.4,
    }
    return _MAP.get(severity, 0.4)


def _blast_radius_score(blast_radius_size: int) -> float:
    """Scale blast radius to [0.0, 1.0] using log10.

    blast_radius_size=0 → 0.0, =10 → ~0.52, =100 → 1.0
    """
    return min(math.log10(blast_radius_size + 1) / math.log10(101), 1.0)


# ---------------------------------------------------------------------------
# Public function: compute_composite_severity
# ---------------------------------------------------------------------------


def compute_composite_severity(severity: str, blast_radius_size: int, domain: str) -> str:
    """Re-weight incident severity using blast radius and domain SLO risk.

    Formula:
        score = base_severity_weight(severity)
              + 0.3 * blast_radius_score(blast_radius_size)
              + 0.2 * slo_risk(domain)

    Thresholds:
        score >= 0.9  → "Sev0"
        score >= 0.7  → "Sev1"
        score >= 0.5  → "Sev2"
        else          → "Sev3"

    Pure function. Never raises.
    """
    slo_risk = _DOMAIN_SLO_RISK.get(domain, _DOMAIN_SLO_RISK_DEFAULT)
    score = (
        _base_severity_weight(severity)
        + 0.3 * _blast_radius_score(blast_radius_size)
        + 0.2 * slo_risk
    )

    if score >= 0.9:
        return "Sev0"
    if score >= 0.7:
        return "Sev1"
    if score >= 0.5:
        return "Sev2"
    return "Sev3"


# ---------------------------------------------------------------------------
# Public function: check_causal_suppression
# ---------------------------------------------------------------------------


async def check_causal_suppression(
    resource_id: str,
    topology_client: Any,
    cosmos_client: Any,
    lookback_hours: int = SUPPRESSION_LOOKBACK_HOURS,
) -> Optional[str]:
    """Check whether a new alert is a downstream cascade of an existing incident.

    Algorithm:
    1. If SUPPRESSION_ENABLED is False, return None immediately.
    2. If topology_client or cosmos_client is None, return None (graceful degrade).
    3. Compute cutoff = now(UTC) - lookback_hours.
    4. Query Cosmos `incidents` container for active incidents within the lookback window.
    5. For each active incident, check if resource_id is in its blast_radius_summary.
    6. Return the parent incident_id on first hit, else None.

    topology_client is accepted for future topology-assisted expansion but is not
    called in Wave 1 (topology blast_radius lookup happens in main.py before this
    function is called).

    Errors:
    - Cosmos query failure → log warning, return None (non-blocking).
    """
    if not SUPPRESSION_ENABLED:
        return None

    if topology_client is None or cosmos_client is None:
        return None

    try:
        cutoff_ts = int(_time.time()) - (lookback_hours * 3600)
        query = (
            "SELECT c.incident_id, c.blast_radius_summary, c.status "
            "FROM c "
            "WHERE c.status NOT IN ('closed', 'suppressed_cascade') "
            "AND c._ts > @cutoff"
        )
        params = [{"name": "@cutoff", "value": cutoff_ts}]

        container = (
            cosmos_client
            .get_database_client(COSMOS_DB_NAME)
            .get_container_client("incidents")
        )

        loop = asyncio.get_running_loop()
        items = await loop.run_in_executor(
            None,
            lambda: list(
                container.query_items(query=query, parameters=params)
            ),
        )

        resource_id_lower = resource_id.lower()

        for incident in items:
            blast_summary = incident.get("blast_radius_summary")
            if blast_summary is None:
                continue
            affected = blast_summary.get("affected_resources", [])
            if resource_id_lower in [r.lower() for r in affected]:
                return incident["incident_id"]

    except Exception as exc:
        logger.warning(
            "check_causal_suppression: Cosmos query failed — skipping suppression check. "
            "resource_id=%s error=%s",
            resource_id,
            exc,
        )

    return None


# ---------------------------------------------------------------------------
# Public function: check_temporal_topological_correlation
# ---------------------------------------------------------------------------


async def check_temporal_topological_correlation(
    resource_id: str,
    domain: str,
    topology_client: Any,
    cosmos_client: Any,
    window_minutes: int = CORRELATION_WINDOW_MINUTES,
) -> Optional[str]:
    """Check whether a new alert should be correlated to an existing incident thread.

    This runs AFTER check_causal_suppression returns None (not suppressed).
    If an existing active incident in the same domain fired within window_minutes
    AND shares at least one topology neighbor with resource_id, route the new alert
    to that existing incident thread rather than creating a new Foundry thread.

    Algorithm:
    1. If SUPPRESSION_ENABLED is False, return None.
    2. If topology_client or cosmos_client is None, return None.
    3. Fetch topology neighbors of resource_id via topology_client._get_topology_node.
       On failure, fall back to single-node set {resource_id.lower()}.
    4. Query Cosmos for recent active incidents in the same domain within window.
    5. For each candidate incident, check if its resource_id or blast_radius resources
       overlap with the neighbor set.
    6. Return first correlation hit's incident_id, else None.

    Errors: log warning, return None (non-blocking).
    """
    if not SUPPRESSION_ENABLED:
        return None

    if topology_client is None or cosmos_client is None:
        return None

    resource_id_lower = resource_id.lower()

    # Step 3: Build neighbor set from topology
    neighbors: set[str] = {resource_id_lower}
    try:
        loop = asyncio.get_running_loop()
        node_doc = await loop.run_in_executor(
            None,
            topology_client._get_topology_node,
            resource_id_lower,
        )
        if node_doc is not None:
            for rel in node_doc.get("relationships", []):
                target = rel.get("target_id")
                if target:
                    neighbors.add(target.lower())
    except Exception as exc:
        logger.warning(
            "check_temporal_topological_correlation: topology fetch failed — "
            "falling back to single-node set. resource_id=%s error=%s",
            resource_id,
            exc,
        )
        # neighbors already contains resource_id_lower — single-node fallback is implicit

    # Step 4: Query Cosmos for recent active incidents in the same domain
    try:
        window_cutoff_ts = int(_time.time()) - (window_minutes * 60)
        query = (
            "SELECT c.incident_id, c.resource_id, c.thread_id, c.blast_radius_summary, c._ts "
            "FROM c "
            "WHERE c.status NOT IN ('closed', 'suppressed_cascade') "
            "AND c.domain = @domain "
            "AND c._ts > @window_cutoff"
        )
        params = [
            {"name": "@domain", "value": domain},
            {"name": "@window_cutoff", "value": window_cutoff_ts},
        ]

        container = (
            cosmos_client
            .get_database_client(COSMOS_DB_NAME)
            .get_container_client("incidents")
        )

        loop = asyncio.get_running_loop()
        candidates = await loop.run_in_executor(
            None,
            lambda: list(
                container.query_items(query=query, parameters=params)
            ),
        )

        # Step 5: Check for neighbor overlap
        for candidate in candidates:
            candidate_resource = (candidate.get("resource_id") or "").lower()

            # 5a: candidate resource_id is in our neighbor set
            if candidate_resource and candidate_resource in neighbors:
                return candidate["incident_id"]

            # 5b: candidate blast_radius affected_resources overlap with neighbors
            blast_summary = candidate.get("blast_radius_summary")
            if blast_summary:
                affected = blast_summary.get("affected_resources", [])
                if resource_id_lower in [r.lower() for r in affected]:
                    return candidate["incident_id"]

    except Exception as exc:
        logger.warning(
            "check_temporal_topological_correlation: Cosmos query failed — "
            "skipping correlation check. resource_id=%s domain=%s error=%s",
            resource_id,
            domain,
            exc,
        )

    return None
