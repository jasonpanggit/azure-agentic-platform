from __future__ import annotations
"""Platform-wide incident pattern analysis — pure Python (PLATINT-001, PLATINT-002, PLATINT-003).

Groups incidents by (domain, resource_type, detection_rule) tuples.
Scores by count * avg_severity. Tracks FinOps estimates. Captures operator feedback.

Architecture:
- Pure functions: _severity_score, _group_incidents_by_pattern, _score_pattern,
  _extract_top_words, _compute_finops_summary, _aggregate_feedback
- analyze_patterns: orchestrates full analysis and writes to Cosmos
- run_pattern_analysis_loop: asyncio background task (mirrors forecaster.py)
"""
import os

import asyncio
import logging
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PATTERN_ANALYSIS_ENABLED: bool = os.environ.get("PATTERN_ANALYSIS_ENABLED", "true").lower() == "true"
PATTERN_ANALYSIS_INTERVAL_SECONDS: int = int(
    os.environ.get("PATTERN_ANALYSIS_INTERVAL_SECONDS", "604800")
)
PATTERN_ANALYSIS_LOOKBACK_DAYS: int = int(
    os.environ.get("PATTERN_ANALYSIS_LOOKBACK_DAYS", "30")
)
FINOPS_SAVINGS_PER_REMEDIATION_MINUTES: float = float(
    os.environ.get("FINOPS_SAVINGS_PER_REMEDIATION_MINUTES", "30")
)
FINOPS_HOURLY_RATE_USD: float = float(
    os.environ.get("FINOPS_HOURLY_RATE_USD", "0.10")
)
COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")
COSMOS_PATTERN_ANALYSIS_CONTAINER: str = os.environ.get(
    "COSMOS_PATTERN_ANALYSIS_CONTAINER", "pattern_analysis"
)

SEVERITY_SCORES: Dict[str, float] = {
    "Sev0": 4.0,
    "Sev1": 3.0,
    "Sev2": 2.0,
    "Sev3": 1.0,
}
DEFAULT_SEVERITY_SCORE: float = 1.5

# Top patterns returned per analysis run
_TOP_PATTERNS_LIMIT = 5

# Minimum word length for top-words extraction (filters stop words)
_MIN_WORD_LENGTH = 4


def _severity_score(severity: str) -> float:
    """Map incident severity string to numeric score.

    Args:
        severity: Severity label, e.g. "Sev0", "Sev1", "Sev2", "Sev3".

    Returns:
        Numeric score from SEVERITY_SCORES, or DEFAULT_SEVERITY_SCORE for unknowns.
    """
    return SEVERITY_SCORES.get(severity, DEFAULT_SEVERITY_SCORE)


def _group_incidents_by_pattern(
    incidents: List[Dict[str, Any]],
) -> Dict[tuple, List[Dict[str, Any]]]:
    """Group incidents by (domain, resource_type, detection_rule) tuple.

    Args:
        incidents: List of incident documents from Cosmos.

    Returns:
        Dict mapping pattern tuple → list of matching incidents.
    """
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for inc in incidents:
        key = (
            inc.get("domain", ""),
            inc.get("resource_type", ""),
            inc.get("detection_rule", ""),
        )
        groups[key].append(inc)
    return dict(groups)


def _score_pattern(incidents: List[Dict[str, Any]]) -> float:
    """Score a pattern group as count * average_severity_score.

    Args:
        incidents: List of incidents belonging to the same pattern.

    Returns:
        Pattern score: len(incidents) * avg_severity_score.
    """
    if not incidents:
        return 0.0
    avg_severity = sum(_severity_score(i.get("severity", "")) for i in incidents) / len(incidents)
    return len(incidents) * avg_severity


def _extract_top_words(
    incidents: List[Dict[str, Any]],
    top_n: int = 5,
) -> List[str]:
    """Extract the top N most frequent words from incident titles.

    Lowercases all words, filters out words with length < _MIN_WORD_LENGTH (4).

    Args:
        incidents: List of incidents with optional "title" field.
        top_n:     Number of top words to return.

    Returns:
        List of top word strings (most frequent first).
    """
    all_words: List[str] = []
    for inc in incidents:
        title = inc.get("title", "") or ""
        words = title.lower().split()
        all_words.extend(w for w in words if len(w) >= _MIN_WORD_LENGTH)
    counter = Counter(all_words)
    return [word for word, _ in counter.most_common(top_n)]


def _compute_finops_summary(
    incidents: List[Dict[str, Any]],
    remediation_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Estimate FinOps cost impact from incidents and remediation records.

    Two estimates (no external API calls):
    - wasted_compute_usd: compute incidents × 0.5h × FINOPS_HOURLY_RATE_USD × avg affected_resources
    - automation_savings_usd: complete remediations × (FINOPS_SAVINGS_PER_REMEDIATION_MINUTES/60) × FINOPS_HOURLY_RATE_USD

    Args:
        incidents:            All incidents from the analysis period.
        remediation_records:  Records from the remediation_audit Cosmos container.

    Returns:
        Dict with keys: wasted_compute_usd, automation_savings_usd,
        complete_remediations, compute_incidents_30min.
    """
    # Count compute domain incidents (simplified — each counted once)
    compute_incidents = [i for i in incidents if (i.get("domain", "")).lower() == "compute"]
    compute_count = len(compute_incidents)

    # Average affected_resources count per compute incident
    avg_affected = 1.0
    if compute_incidents:
        total_affected = sum(
            len(i.get("affected_resources", []) or []) or 1
            for i in compute_incidents
        )
        avg_affected = total_affected / len(compute_incidents)

    # wasted_compute_usd = count × 0.5h × hourly_rate × avg_affected
    wasted = compute_count * 0.5 * FINOPS_HOURLY_RATE_USD * avg_affected

    # automation_savings_usd: complete remediations × (savings_minutes/60) × hourly_rate
    complete_count = sum(
        1 for r in remediation_records if r.get("status") == "complete"
    )
    savings = complete_count * (FINOPS_SAVINGS_PER_REMEDIATION_MINUTES / 60.0) * FINOPS_HOURLY_RATE_USD

    return {
        "wasted_compute_usd": round(wasted, 2),
        "automation_savings_usd": round(savings, 2),
        "complete_remediations": complete_count,
        "compute_incidents_30min": compute_count,
    }


def _aggregate_feedback(
    approval_records: List[Dict[str, Any]],
    pattern_key: tuple,
) -> tuple[bool, List[str]]:
    """Aggregate operator feedback tags for approvals matching a pattern.

    Matches approvals where the associated incident's domain, resource_type,
    and detection_rule match the pattern_key tuple.

    operator_flagged = True when >= 2 approvals have "false_positive" or
    "not_useful" in their feedback_tags.

    Args:
        approval_records: Approval docs from Cosmos (may have feedback_tags field).
        pattern_key:      (domain, resource_type, detection_rule) tuple.

    Returns:
        Tuple of (operator_flagged: bool, common_feedback: list[str]).
    """
    domain, resource_type, detection_rule = pattern_key

    matching: List[Dict[str, Any]] = []
    for approval in approval_records:
        # Match on incident context fields stored in the approval doc
        if (
            approval.get("domain", "") == domain
            and approval.get("resource_type", "") == resource_type
            and approval.get("detection_rule", "") == detection_rule
        ):
            matching.append(approval)

    # Collect all feedback tags from matching approvals
    all_tags: List[str] = []
    negative_count = 0
    for approval in matching:
        tags = approval.get("feedback_tags") or []
        all_tags.extend(tags)
        if any(t in ("false_positive", "not_useful") for t in tags):
            negative_count += 1

    operator_flagged = negative_count >= 2

    # Top-3 most common feedback tags
    tag_counter = Counter(all_tags)
    common_feedback = [tag for tag, _ in tag_counter.most_common(3)]

    return operator_flagged, common_feedback


def compute_mttr_by_issue_type(
    incidents: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute MTTR (Mean Time To Resolution) statistics grouped by issue type.

    Groups resolved incidents by (domain, detection_rule, severity) and computes
    P50, P95, and mean MTTR in minutes.

    Only includes incidents where both created_at and resolved_at are present.

    Args:
        incidents: List of incident documents from Cosmos.

    Returns:
        Dict mapping "domain:detection_rule:severity" → {
            "count": int,
            "p50_min": float,
            "p95_min": float,
            "mean_min": float,
        }
    """
    from datetime import datetime as _dt

    groups: Dict[str, List[float]] = defaultdict(list)

    for inc in incidents:
        created_at = inc.get("created_at")
        resolved_at = inc.get("resolved_at")
        if not created_at or not resolved_at:
            continue
        if inc.get("status") != "resolved":
            continue

        try:
            created = _dt.fromisoformat(created_at.replace("Z", "+00:00"))
            resolved = _dt.fromisoformat(resolved_at.replace("Z", "+00:00"))
            mttr_minutes = (resolved - created).total_seconds() / 60.0
            if mttr_minutes < 0:
                continue
        except (ValueError, TypeError):
            continue

        domain = inc.get("domain", "unknown")
        detection_rule = inc.get("detection_rule", "unknown")
        severity = inc.get("severity", "unknown")
        key = f"{domain}:{detection_rule}:{severity}"
        groups[key].append(mttr_minutes)

    result: Dict[str, Dict[str, Any]] = {}
    for key, times in groups.items():
        if not times:
            continue
        sorted_times = sorted(times)
        n = len(sorted_times)
        p50_idx = int(n * 0.50)
        p95_idx = min(int(n * 0.95), n - 1)
        result[key] = {
            "count": n,
            "p50_min": round(sorted_times[p50_idx], 1),
            "p95_min": round(sorted_times[p95_idx], 1),
            "mean_min": round(sum(sorted_times) / n, 1),
        }

    return result


def _query_cosmos_container(
    cosmos_client: Any,
    container_name: str,
    query: str,
    parameters: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Synchronous helper to query a Cosmos container.

    Designed to be called from run_in_executor.

    Returns:
        List of matching documents, or empty list on error.
    """
    try:
        db = cosmos_client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(container_name)
        kwargs: Dict[str, Any] = {"enable_cross_partition_query": True}
        if parameters:
            kwargs["parameters"] = parameters
        items = list(container.query_items(query=query, **kwargs))
        return items
    except Exception as exc:
        logger.warning(
            "pattern_analyzer: cosmos query failed | container=%s error=%s",
            container_name,
            exc,
        )
        return []


def _upsert_cosmos_doc(
    cosmos_client: Any,
    container_name: str,
    doc: Dict[str, Any],
) -> None:
    """Synchronous helper to upsert a document into a Cosmos container.

    Designed to be called from run_in_executor.
    """
    try:
        db = cosmos_client.get_database_client(COSMOS_DATABASE)
        container = db.get_container_client(container_name)
        container.upsert_item(doc)
    except Exception as exc:
        logger.warning(
            "pattern_analyzer: cosmos upsert failed | container=%s error=%s",
            container_name,
            exc,
        )


def _run_analysis_sync(cosmos_client: Any) -> Optional[Dict[str, Any]]:
    """Synchronous analysis body — runs in executor thread.

    1. Reads incidents from last PATTERN_ANALYSIS_LOOKBACK_DAYS days.
    2. Reads remediation_audit records (last 30 days, action_type=execute).
    3. Reads approval records (last 30 days).
    4. Groups incidents by pattern, scores, takes top-5.
    5. For each pattern, aggregates operator feedback.
    6. Computes FinOps summary.
    7. Builds and upserts PatternAnalysisResult doc to Cosmos.

    Returns the doc dict, or None on error.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=PATTERN_ANALYSIS_LOOKBACK_DAYS)).isoformat()
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    analysis_date = now.strftime("%Y-%m-%d")

    # --- Read incidents ---
    incidents = _query_cosmos_container(
        cosmos_client,
        "incidents",
        "SELECT * FROM c WHERE c.created_at >= @cutoff",
        parameters=[{"name": "@cutoff", "value": cutoff}],
    )

    # --- Read remediation records ---
    remediation_records = _query_cosmos_container(
        cosmos_client,
        "remediation_audit",
        "SELECT * FROM c WHERE c.executed_at >= @cutoff AND c.action_type = @action_type",
        parameters=[
            {"name": "@cutoff", "value": cutoff_30d},
            {"name": "@action_type", "value": "execute"},
        ],
    )

    # --- Read approval records ---
    approval_records = _query_cosmos_container(
        cosmos_client,
        "approvals",
        "SELECT * FROM c WHERE c.proposed_at >= @cutoff",
        parameters=[{"name": "@cutoff", "value": cutoff_30d}],
    )

    # --- Group and score patterns ---
    groups = _group_incidents_by_pattern(incidents)

    # Score each pattern and sort descending
    scored = sorted(
        groups.items(),
        key=lambda kv: _score_pattern(kv[1]),
        reverse=True,
    )

    top_patterns = []
    for pattern_key, group_incidents in scored[:_TOP_PATTERNS_LIMIT]:
        domain, resource_type, detection_rule = pattern_key
        score = _score_pattern(group_incidents)

        # Time bounds
        timestamps = [i.get("created_at", "") for i in group_incidents if i.get("created_at")]
        first_seen = min(timestamps) if timestamps else now.isoformat()
        last_seen = max(timestamps) if timestamps else now.isoformat()

        # Average severity score
        avg_severity = score / len(group_incidents) if group_incidents else 0.0

        # Frequency: incidents per week over the lookback period
        weeks = max(PATTERN_ANALYSIS_LOOKBACK_DAYS / 7.0, 1.0)
        frequency_per_week = len(group_incidents) / weeks

        # Top words from titles
        top_words = _extract_top_words(group_incidents)

        # Operator feedback aggregation
        operator_flagged, common_feedback = _aggregate_feedback(approval_records, pattern_key)

        pattern_id = str(uuid.uuid4())
        top_patterns.append({
            "pattern_id": pattern_id,
            "domain": domain,
            "resource_type": resource_type if resource_type else None,
            "detection_rule": detection_rule if detection_rule else None,
            "incident_count": len(group_incidents),
            "frequency_per_week": round(frequency_per_week, 2),
            "avg_severity_score": round(avg_severity, 2),
            "top_title_words": top_words,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "operator_flagged": operator_flagged,
            "common_feedback": common_feedback,
        })

    # --- FinOps summary ---
    finops_dict = _compute_finops_summary(incidents, remediation_records)

    # --- MTTR summary ---
    mttr_dict = compute_mttr_by_issue_type(incidents)

    # --- Build result doc ---
    doc = {
        "id": f"pattern-{analysis_date}",
        "analysis_date": analysis_date,
        "analysis_id": f"pattern-{analysis_date}",
        "period_days": PATTERN_ANALYSIS_LOOKBACK_DAYS,
        "total_incidents_analyzed": len(incidents),
        "top_patterns": top_patterns,
        "finops_summary": finops_dict,
        "mttr_summary": mttr_dict,
        "generated_at": now.isoformat(),
    }

    # --- Upsert to Cosmos ---
    _upsert_cosmos_doc(cosmos_client, COSMOS_PATTERN_ANALYSIS_CONTAINER, doc)

    logger.info(
        "pattern_analyzer: analysis complete | date=%s incidents=%d patterns=%d",
        analysis_date,
        len(incidents),
        len(top_patterns),
    )
    return doc


async def analyze_patterns(cosmos_client: Any) -> Optional[Dict[str, Any]]:
    """Orchestrate a full pattern analysis run and write result to Cosmos.

    Reads incidents, remediation records, and approvals from Cosmos.
    Groups by (domain, resource_type, detection_rule), scores patterns,
    takes top-5, aggregates operator feedback, computes FinOps summary.

    Args:
        cosmos_client: CosmosClient instance (or None for tests).

    Returns:
        PatternAnalysisResult dict written to Cosmos, or None on error.
    """
    if cosmos_client is None:
        logger.warning("pattern_analyzer: analyze_patterns skipped (no cosmos_client)")
        return None

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_analysis_sync, cosmos_client)
        return result
    except Exception as exc:
        logger.error(
            "pattern_analyzer: analyze_patterns failed | error=%s", exc, exc_info=True
        )
        return None


async def run_pattern_analysis_loop(
    cosmos_client: Any,
    interval_seconds: int = PATTERN_ANALYSIS_INTERVAL_SECONDS,
) -> None:
    """Background asyncio task: run pattern analysis on a weekly interval.

    Mirrors run_forecast_sweep_loop in forecaster.py:
    - Waits one full interval before first run.
    - Handles CancelledError cleanly for graceful shutdown.
    - Logs but does not raise on transient errors (loop continues).

    If PATTERN_ANALYSIS_ENABLED=false, logs and exits immediately.

    Args:
        cosmos_client:    CosmosClient instance (from app.state).
        interval_seconds: Analysis interval in seconds (default 604800 — 7 days).
    """
    if not PATTERN_ANALYSIS_ENABLED:
        logger.info("pattern_analyzer: loop disabled (PATTERN_ANALYSIS_ENABLED=false)")
        return

    logger.info(
        "pattern_analyzer: loop started | interval=%ds", interval_seconds
    )

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await analyze_patterns(cosmos_client)
        except asyncio.CancelledError:
            logger.info("pattern_analyzer: loop cancelled — shutting down")
            raise
        except Exception as exc:
            logger.error(
                "pattern_analyzer: loop unexpected error | error=%s", exc, exc_info=True
            )
            # Continue loop — transient errors must not stop the background task
