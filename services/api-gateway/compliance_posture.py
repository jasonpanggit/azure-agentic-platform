from __future__ import annotations
"""Compliance posture computation logic (Phase 54).

Separates business logic from routing following the project convention.
Contains:
- fetch_defender_assessments: live Defender for Cloud assessment data
- fetch_policy_compliance: live Azure Policy compliance state
- compute_posture: pure function that maps findings to CIS/NIST/ASB controls
- In-memory posture cache (1h TTL) and mappings cache (24h TTL)
- get_compliance_mappings: load mapping rows from PostgreSQL
"""
import os

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy SDK imports — SDKs may not be installed in all environments
# ---------------------------------------------------------------------------

try:
    from azure.mgmt.security import SecurityCenter  # type: ignore[import]
    _SECURITY_IMPORT_ERROR: str = ""
except Exception as _e:  # noqa: BLE001
    SecurityCenter = None  # type: ignore[assignment,misc]
    _SECURITY_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.policyinsights import PolicyInsightsClient  # type: ignore[import]
    from azure.mgmt.policyinsights.models import QueryOptions  # type: ignore[import]
    _POLICY_IMPORT_ERROR: str = ""
except Exception as _e:  # noqa: BLE001
    PolicyInsightsClient = None  # type: ignore[assignment,misc]
    QueryOptions = None  # type: ignore[assignment,misc]
    _POLICY_IMPORT_ERROR = str(_e)

if SecurityCenter is None:
    logger.warning(
        "azure-mgmt-security unavailable — Defender assessments will return empty: %s",
        _SECURITY_IMPORT_ERROR or "ImportError",
    )
if PolicyInsightsClient is None:
    logger.warning(
        "azure-mgmt-policyinsights unavailable — Policy compliance will return empty: %s",
        _POLICY_IMPORT_ERROR or "ImportError",
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAMEWORK_COLUMNS: dict[str, tuple[str, str]] = {
    "asb": ("asb_control_id", "asb_title"),
    "cis": ("cis_control_id", "cis_title"),
    "nist": ("nist_control_id", "nist_title"),
}

POSTURE_CACHE_TTL_SECONDS: int = 3600   # 1 hour
MAPPINGS_CACHE_TTL_SECONDS: int = 86400  # 24 hours

# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

# (result_dict, timestamp_float)
_posture_cache: dict[str, tuple[float, dict[str, Any]]] = {}
# Single entry for mappings (changes rarely)
_mappings_cache: Optional[tuple[float, list[dict[str, Any]]]] = None


def get_cached_posture(subscription_id: str) -> Optional[dict[str, Any]]:
    """Return cached posture result if still fresh, else None."""
    entry = _posture_cache.get(subscription_id)
    if entry is None:
        return None
    stored_at, result = entry
    if time.monotonic() - stored_at < POSTURE_CACHE_TTL_SECONDS:
        return result
    del _posture_cache[subscription_id]
    return None


def set_cached_posture(subscription_id: str, result: dict[str, Any]) -> None:
    """Store posture result in cache with current timestamp."""
    _posture_cache[subscription_id] = (time.monotonic(), result)


# ---------------------------------------------------------------------------
# PostgreSQL helpers
# ---------------------------------------------------------------------------

def _resolve_dsn() -> str:
    """Resolve PostgreSQL DSN from environment variables."""
    for env in ("PGVECTOR_CONNECTION_STRING", "POSTGRES_DSN"):
        val = os.environ.get(env, "").strip()
        if val:
            return val
    host = os.environ.get("POSTGRES_HOST", "").strip()
    if host:
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "aap")
        user = os.environ.get("POSTGRES_USER", "aap")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    raise RuntimeError(
        "PostgreSQL not configured — set PGVECTOR_CONNECTION_STRING, "
        "POSTGRES_DSN, or POSTGRES_HOST."
    )


async def get_compliance_mappings(dsn: Optional[str] = None) -> list[dict[str, Any]]:
    """Load all compliance mapping rows from PostgreSQL.

    Results are cached in-memory for 24h since mappings change infrequently.
    """
    global _mappings_cache  # noqa: PLW0603

    # Return from cache if fresh
    if _mappings_cache is not None:
        stored_at, rows = _mappings_cache
        if time.monotonic() - stored_at < MAPPINGS_CACHE_TTL_SECONDS:
            return rows

    import asyncpg  # noqa: PLC0415

    resolved_dsn = dsn or _resolve_dsn()
    conn = await asyncpg.connect(resolved_dsn)
    try:
        records = await conn.fetch(
            """
            SELECT finding_type, defender_rule_id, display_name, description,
                   cis_control_id, cis_title, nist_control_id, nist_title,
                   asb_control_id, asb_title, severity
            FROM compliance_mappings
            ORDER BY finding_type, asb_control_id NULLS LAST
            """
        )
        rows = [dict(r) for r in records]
    finally:
        await conn.close()

    _mappings_cache = (time.monotonic(), rows)
    logger.info("Loaded %d compliance mappings from PostgreSQL", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Live data fetchers
# ---------------------------------------------------------------------------

async def fetch_defender_assessments(
    credential: Any, subscription_id: str
) -> list[dict[str, Any]]:
    """Fetch Defender for Cloud assessment results for a subscription.

    Returns a list of dicts with keys:
        name, display_name, status (Healthy|Unhealthy|NotApplicable), severity
    Returns empty list if SDK unavailable or any exception occurs.
    """
    if SecurityCenter is None:
        logger.debug("SecurityCenter SDK unavailable — returning empty assessments")
        return []

    try:
        client = SecurityCenter(credential=credential, subscription_id=subscription_id)
        results: list[dict[str, Any]] = []
        for assessment in client.assessments.list(scope=f"/subscriptions/{subscription_id}"):
            status = "NotApplicable"
            if assessment.status:
                status = assessment.status.code or "NotApplicable"
            display_name = ""
            if assessment.display_name:
                display_name = assessment.display_name
            elif assessment.metadata and assessment.metadata.display_name:
                display_name = assessment.metadata.display_name
            results.append({
                "name": assessment.name or "",
                "display_name": display_name,
                "status": status,
                "severity": (
                    assessment.metadata.severity
                    if assessment.metadata and assessment.metadata.severity
                    else "Medium"
                ),
            })
        logger.debug(
            "Fetched %d Defender assessments for subscription %s",
            len(results), subscription_id,
        )
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to fetch Defender assessments for %s: %s",
            subscription_id, exc,
        )
        return []


async def fetch_policy_compliance(
    credential: Any, subscription_id: str
) -> list[dict[str, Any]]:
    """Fetch non-compliant Azure Policy states for a subscription.

    Returns a list of dicts with keys:
        policy_definition_name, compliance_state, resource_id
    Returns empty list if SDK unavailable or any exception occurs.
    """
    if PolicyInsightsClient is None:
        logger.debug("PolicyInsightsClient SDK unavailable — returning empty policy states")
        return []

    try:
        client = PolicyInsightsClient(credential=credential)
        query_opts = None
        if QueryOptions is not None:
            query_opts = QueryOptions(
                top=1000,
                filter="complianceState eq 'NonCompliant'",
            )
        results: list[dict[str, Any]] = []
        for state in client.policy_states.list_query_results_for_subscription(
            "latest",
            subscription_id,
            query_options=query_opts,
        ):
            results.append({
                "policy_definition_name": state.policy_definition_name or "",
                "compliance_state": state.compliance_state or "NonCompliant",
                "resource_id": state.resource_id or "",
            })
        logger.debug(
            "Fetched %d non-compliant policy states for subscription %s",
            len(results), subscription_id,
        )
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to fetch policy compliance for %s: %s",
            subscription_id, exc,
        )
        return []


# ---------------------------------------------------------------------------
# Core posture computation — pure function (no SDK / I/O)
# ---------------------------------------------------------------------------

def compute_posture(
    mappings: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
    policy_states: list[dict[str, Any]],
    subscription_id: str = "",
) -> dict[str, Any]:
    """Compute compliance posture from mapping rows + live findings.

    This is a pure function: it takes already-fetched data and returns a
    structured posture report. No SDK calls are made here.

    Args:
        mappings: Rows from the compliance_mappings PostgreSQL table.
        assessments: Live Defender assessment dicts from fetch_defender_assessments.
        policy_states: Live non-compliant policy states from fetch_policy_compliance.
        subscription_id: For labelling the response.

    Returns:
        Posture dict with shape:
        {
          "subscription_id": str,
          "generated_at": iso_timestamp,
          "frameworks": {
            "asb": {"score": float, "total_controls": int, "passing": int,
                    "failing": int, "not_assessed": int},
            "cis": {...}, "nist": {...},
          },
          "controls": [
            {"framework": str, "control_id": str, "control_title": str,
             "status": str,   # passing | failing | not_assessed
             "findings": [{"finding_type": str, "defender_rule_id": str,
                           "display_name": str, "severity": str}]}
          ]
        }
    """
    # Build lookup maps for fast matching
    # Defender: index by display_name (lowercase) and by name/rule_id
    assessment_map: dict[str, str] = {}  # display_name_lower → status
    for a in assessments:
        key = a.get("display_name", "").lower().strip()
        if key:
            assessment_map[key] = a.get("status", "NotApplicable")

    # Policy: index by policy_definition_name
    noncompliant_policies: set[str] = {
        s.get("policy_definition_name", "").lower()
        for s in policy_states
        if s.get("compliance_state") in ("NonCompliant", "noncompliant")
    }

    def _status_for_mapping(row: dict[str, Any]) -> str:
        """Determine passing/failing/not_assessed for a single mapping row."""
        finding_type = row.get("finding_type", "")
        display_name_lower = row.get("display_name", "").lower().strip()
        rule_id_lower = (row.get("defender_rule_id") or "").lower().strip()

        if finding_type == "defender_assessment":
            status = assessment_map.get(display_name_lower)
            if status is None and rule_id_lower:
                status = assessment_map.get(rule_id_lower)
            if status is None:
                return "not_assessed"
            return "passing" if status == "Healthy" else "failing"

        if finding_type == "policy":
            match_key = display_name_lower or rule_id_lower
            if not match_key:
                return "not_assessed"
            # If found in noncompliant set → failing; if not in set → passing
            # (absence from NonCompliant list means compliant)
            return "failing" if match_key in noncompliant_policies else "passing"

        if finding_type == "advisor":
            # Advisor findings: not tracked live in this phase → not_assessed
            return "not_assessed"

        return "not_assessed"

    # Aggregate per (framework, control_id)
    # Structure: { (fw, ctrl_id): {"title": str, "statuses": [str], "findings": [...]} }
    control_data: dict[tuple[str, str], dict[str, Any]] = {}

    for row in mappings:
        finding_status = _status_for_mapping(row)
        finding_entry = {
            "finding_type": row.get("finding_type", ""),
            "defender_rule_id": row.get("defender_rule_id") or "",
            "display_name": row.get("display_name", ""),
            "severity": row.get("severity", "Medium"),
        }

        for fw_name, (ctrl_col, title_col) in FRAMEWORK_COLUMNS.items():
            ctrl_id = row.get(ctrl_col)
            if not ctrl_id:
                continue
            ctrl_title = row.get(title_col) or ""
            key = (fw_name, ctrl_id)
            if key not in control_data:
                control_data[key] = {
                    "title": ctrl_title,
                    "statuses": [],
                    "findings": [],
                }
            control_data[key]["statuses"].append(finding_status)
            control_data[key]["findings"].append(finding_entry)

    # Build controls list and framework summary
    controls: list[dict[str, Any]] = []
    framework_stats: dict[str, dict[str, Any]] = {
        fw: {"passing": 0, "failing": 0, "not_assessed": 0}
        for fw in FRAMEWORK_COLUMNS
    }

    for (fw_name, ctrl_id), data in sorted(control_data.items(), key=lambda x: (x[0][0], x[0][1])):
        statuses = data["statuses"]

        # Control status: failing if ANY finding fails, passing if all pass, else not_assessed
        if "failing" in statuses:
            ctrl_status = "failing"
        elif all(s == "not_assessed" for s in statuses):
            ctrl_status = "not_assessed"
        else:
            ctrl_status = "passing"

        framework_stats[fw_name][ctrl_status] += 1

        controls.append({
            "framework": fw_name,
            "control_id": ctrl_id,
            "control_title": data["title"],
            "status": ctrl_status,
            "findings": data["findings"],
        })

    # Compute per-framework scores
    frameworks: dict[str, Any] = {}
    for fw_name, stats in framework_stats.items():
        passing = stats["passing"]
        failing = stats["failing"]
        not_assessed = stats["not_assessed"]
        total = passing + failing + not_assessed
        assessed = passing + failing
        score = round((passing / assessed * 100) if assessed > 0 else 0.0, 1)
        frameworks[fw_name] = {
            "score": score,
            "total_controls": total,
            "passing": passing,
            "failing": failing,
            "not_assessed": not_assessed,
        }

    return {
        "subscription_id": subscription_id,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "frameworks": frameworks,
        "controls": controls,
    }
