from __future__ import annotations
"""Cross-subscription alert correlator — Phase 86.

Detects subscription_storm and blast_radius patterns in recent incidents.
Never raises from public functions.
"""

import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COSMOS_INCIDENTS_CONTAINER = "incidents"
COSMOS_CORRELATION_GROUPS_CONTAINER = "correlation_groups"

# Storm thresholds
STORM_MIN_SUBSCRIPTIONS = 3          # same (resource_type, domain) in N+ subscriptions
BLAST_RADIUS_MIN_RG = 5              # same resource_type in 1 sub but N+ resource_groups
WINDOW_MINUTES = 15                  # sliding window for grouping
DECAY_HALF_LIFE_MINUTES = 30         # exp decay half-life for scoring


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CorrelationGroup:
    group_id: str
    pattern: str            # subscription_storm | blast_radius | cluster
    title: str
    incident_ids: List[str]
    subscription_ids: List[str]
    resource_type: str
    domain: str
    time_window_start: str
    time_window_end: str
    score: float            # 0.0–1.0
    affected_count: int
    recommended_action: str
    detected_at: str
    ttl: int = 7200         # 2 hours


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_container(cosmos_client: Any, db_name: str, container_name: str) -> Any:
    return (
        cosmos_client
        .get_database_client(db_name)
        .get_container_client(container_name)
    )


def _ensure_correlation_container(cosmos_client: Any, db_name: str) -> Any:
    """Return correlation_groups container, creating it if absent."""
    try:
        db = cosmos_client.get_database_client(db_name)
        return db.create_container_if_not_exists(
            id=COSMOS_CORRELATION_GROUPS_CONTAINER,
            partition_key={"paths": ["/pattern"], "kind": "Hash"},
            default_ttl=7200,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Could not ensure correlation_groups container: %s", exc)
        return cosmos_client.get_database_client(db_name).get_container_client(
            COSMOS_CORRELATION_GROUPS_CONTAINER
        )


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, return None on failure."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            if ts.endswith("Z"):
                ts_clean = ts[:-1] + "+00:00"
            else:
                ts_clean = ts
            return datetime.fromisoformat(ts_clean)
        except ValueError:
            continue
    return None


def _recency_score(age_minutes: float) -> float:
    """Exponential decay: score = exp(-age / half_life * ln2)."""
    return math.exp(-age_minutes * math.log(2) / DECAY_HALF_LIFE_MINUTES)


def _recommended_action(pattern: str, resource_type: str, domain: str) -> str:
    if pattern == "subscription_storm":
        return (
            f"Investigate shared infrastructure for {resource_type} across subscriptions "
            f"(VNet, ExpressRoute, DNS, shared services). Likely platform-level issue."
        )
    if pattern == "blast_radius":
        return (
            f"Scope blast-radius containment for {resource_type} in {domain} domain. "
            f"Check for noisy-neighbour or shared dependency within subscription."
        )
    return f"Investigate correlated {resource_type} incidents in {domain} domain."


def _group_incidents_into_correlation_groups(
    incidents: List[Dict[str, Any]],
    now: datetime,
) -> List[CorrelationGroup]:
    """Apply grouping logic and return CorrelationGroup list."""
    # Sort by time
    timed: List[Dict[str, Any]] = []
    for inc in incidents:
        ts = _parse_iso(inc.get("created_at", ""))
        if ts:
            timed.append({**inc, "_ts": ts})

    timed.sort(key=lambda x: x["_ts"])
    groups: List[CorrelationGroup] = []

    # ---- subscription_storm detection ----
    # Group by (resource_type, domain), then scan for 3+ subscriptions in any 15-min window
    type_domain_buckets: Dict[str, List[Dict[str, Any]]] = {}
    for inc in timed:
        key = f"{inc.get('resource_type','unknown')}|{inc.get('domain','unknown')}"
        type_domain_buckets.setdefault(key, []).append(inc)

    seen_incident_ids_storm: set = set()

    for key, bucket in type_domain_buckets.items():
        resource_type, domain = key.split("|", 1)
        # Slide window
        for i, anchor in enumerate(bucket):
            window_end = anchor["_ts"] + timedelta(minutes=WINDOW_MINUTES)
            window_items = [b for b in bucket[i:] if b["_ts"] <= window_end]
            sub_ids = list({b.get("subscription_id", "") for b in window_items if b.get("subscription_id")})
            if len(sub_ids) >= STORM_MIN_SUBSCRIPTIONS:
                ids = [b.get("incident_id", b.get("id", "")) for b in window_items]
                # Avoid near-duplicate groups (overlap > 50%)
                if any(iid in seen_incident_ids_storm for iid in ids):
                    continue
                seen_incident_ids_storm.update(ids)
                age_minutes = (now - anchor["_ts"]).total_seconds() / 60
                score = min(1.0, (len(sub_ids) / 10) * _recency_score(age_minutes))
                groups.append(CorrelationGroup(
                    group_id=str(uuid.uuid4()),
                    pattern="subscription_storm",
                    title=f"Subscription storm: {resource_type} ({domain})",
                    incident_ids=ids,
                    subscription_ids=sub_ids,
                    resource_type=resource_type,
                    domain=domain,
                    time_window_start=anchor["_ts"].isoformat(),
                    time_window_end=window_end.isoformat(),
                    score=round(score, 3),
                    affected_count=len(sub_ids),
                    recommended_action=_recommended_action("subscription_storm", resource_type, domain),
                    detected_at=now.isoformat(),
                ))
                break  # one storm group per (resource_type, domain)

    # ---- blast_radius detection ----
    # Same resource_type in 1 subscription but 5+ distinct resource_groups
    sub_type_buckets: Dict[str, List[Dict[str, Any]]] = {}
    for inc in timed:
        key = f"{inc.get('subscription_id','unknown')}|{inc.get('resource_type','unknown')}"
        sub_type_buckets.setdefault(key, []).append(inc)

    for key, bucket in sub_type_buckets.items():
        sub_id, resource_type = key.split("|", 1)
        rgs = list({b.get("resource_group", "") for b in bucket if b.get("resource_group")})
        if len(rgs) >= BLAST_RADIUS_MIN_RG:
            domain = bucket[0].get("domain", "unknown")
            ids = [b.get("incident_id", b.get("id", "")) for b in bucket]
            ts_sorted = sorted(b["_ts"] for b in bucket)
            age_minutes = (now - ts_sorted[0]).total_seconds() / 60
            score = min(1.0, (len(rgs) / 15) * _recency_score(age_minutes))
            groups.append(CorrelationGroup(
                group_id=str(uuid.uuid4()),
                pattern="blast_radius",
                title=f"Blast radius: {resource_type} across {len(rgs)} resource groups",
                incident_ids=ids,
                subscription_ids=[sub_id],
                resource_type=resource_type,
                domain=domain,
                time_window_start=ts_sorted[0].isoformat(),
                time_window_end=ts_sorted[-1].isoformat(),
                score=round(score, 3),
                affected_count=len(rgs),
                recommended_action=_recommended_action("blast_radius", resource_type, domain),
                detected_at=now.isoformat(),
            ))

    return groups


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def detect_correlation_groups(
    cosmos_client: Any,
    db_name: str,
    window_minutes: int = 120,
) -> List[CorrelationGroup]:
    """Read recent incidents and detect correlation groups. Never raises."""
    start = time.monotonic()
    try:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(minutes=window_minutes)).isoformat()

        container = _get_container(cosmos_client, db_name, COSMOS_INCIDENTS_CONTAINER)
        query = (
            "SELECT c.incident_id, c.id, c.resource_type, c.domain, "
            "c.subscription_id, c.resource_group, c.created_at, c.alert_type "
            "FROM c WHERE c.created_at >= @cutoff"
        )
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@cutoff", "value": cutoff}],
            enable_cross_partition_query=True,
        ))
        groups = _group_incidents_into_correlation_groups(items, now)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "detect_correlation_groups found %d groups from %d incidents in %.1f ms",
            len(groups), len(items), duration_ms,
        )
        return groups
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error("detect_correlation_groups failed after %.1f ms: %s", duration_ms, exc)
        return []


def get_active_groups(
    cosmos_client: Any,
    db_name: str,
) -> List[CorrelationGroup]:
    """Read persisted active correlation groups from Cosmos. Never raises."""
    start = time.monotonic()
    try:
        container = _ensure_correlation_container(cosmos_client, db_name)
        query = "SELECT * FROM c ORDER BY c.detected_at DESC"
        items = list(container.query_items(
            query=query,
            enable_cross_partition_query=True,
        ))
        groups = []
        for doc in items:
            groups.append(CorrelationGroup(
                group_id=doc.get("group_id", doc.get("id", "")),
                pattern=doc.get("pattern", "cluster"),
                title=doc.get("title", ""),
                incident_ids=doc.get("incident_ids", []),
                subscription_ids=doc.get("subscription_ids", []),
                resource_type=doc.get("resource_type", ""),
                domain=doc.get("domain", ""),
                time_window_start=doc.get("time_window_start", ""),
                time_window_end=doc.get("time_window_end", ""),
                score=float(doc.get("score", 0.0)),
                affected_count=int(doc.get("affected_count", 0)),
                recommended_action=doc.get("recommended_action", ""),
                detected_at=doc.get("detected_at", ""),
                ttl=int(doc.get("ttl", 7200)),
            ))
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("get_active_groups returned %d groups in %.1f ms", len(groups), duration_ms)
        return groups
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error("get_active_groups failed after %.1f ms: %s", duration_ms, exc)
        return []


def persist_groups(
    cosmos_client: Any,
    db_name: str,
    groups: List[CorrelationGroup],
) -> None:
    """Upsert correlation groups to Cosmos. Never raises."""
    if not groups:
        return
    start = time.monotonic()
    try:
        container = _ensure_correlation_container(cosmos_client, db_name)
        for g in groups:
            doc = {
                "id": g.group_id,
                "group_id": g.group_id,
                "pattern": g.pattern,
                "title": g.title,
                "incident_ids": g.incident_ids,
                "subscription_ids": g.subscription_ids,
                "resource_type": g.resource_type,
                "domain": g.domain,
                "time_window_start": g.time_window_start,
                "time_window_end": g.time_window_end,
                "score": g.score,
                "affected_count": g.affected_count,
                "recommended_action": g.recommended_action,
                "detected_at": g.detected_at,
                "ttl": g.ttl,
            }
            container.upsert_item(doc)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("persist_groups saved %d groups in %.1f ms", len(groups), duration_ms)
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error("persist_groups failed after %.1f ms: %s", duration_ms, exc)


def get_correlation_summary(
    cosmos_client: Any,
    db_name: str,
) -> Dict[str, Any]:
    """Return high-level correlation summary. Never raises."""
    start = time.monotonic()
    try:
        groups = get_active_groups(cosmos_client, db_name)
        storms = [g for g in groups if g.pattern == "subscription_storm"]
        blast = [g for g in groups if g.pattern == "blast_radius"]
        total_correlated = sum(len(g.incident_ids) for g in groups)

        # top affected resource type
        type_counts: Dict[str, int] = {}
        for g in groups:
            type_counts[g.resource_type] = type_counts.get(g.resource_type, 0) + len(g.incident_ids)
        top_type = max(type_counts, key=lambda k: type_counts[k]) if type_counts else None

        duration_ms = (time.monotonic() - start) * 1000
        logger.info("get_correlation_summary computed in %.1f ms", duration_ms)
        return {
            "active_storms": len(storms),
            "blast_radius_events": len(blast),
            "total_correlated_incidents": total_correlated,
            "top_affected_resource_type": top_type,
            "total_groups": len(groups),
        }
    except Exception as exc:  # pylint: disable=broad-except
        duration_ms = (time.monotonic() - start) * 1000
        logger.error("get_correlation_summary failed after %.1f ms: %s", duration_ms, exc)
        return {
            "active_storms": 0,
            "blast_radius_events": 0,
            "total_correlated_incidents": 0,
            "top_affected_resource_type": None,
            "total_groups": 0,
        }
