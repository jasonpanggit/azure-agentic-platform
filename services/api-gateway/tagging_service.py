from __future__ import annotations
"""Resource Tagging Compliance Service (Phase 75).

Scans all Azure resources via ARG and evaluates them against a mandatory tag
schema. Provides compliance summarisation and Azure CLI remediation script
generation.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level SDK availability (matches project pattern for mockability)
# ---------------------------------------------------------------------------

try:
    from services.api_gateway.arg_helper import run_arg_query
except ImportError:  # pragma: no cover
    run_arg_query = None  # type: ignore[assignment]


def _log_sdk_availability() -> None:
    if run_arg_query is None:
        logger.warning("tagging_service: arg_helper unavailable — ARG queries disabled")


_log_sdk_availability()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REQUIRED_TAGS: list[str] = ["Environment", "Owner", "CostCenter", "Application"]

_ARG_KQL = """
Resources
| where type !in~ (
    'microsoft.resources/subscriptions',
    'microsoft.resources/resourcegroups',
    'microsoft.resources/tenants'
  )
| project
    id = tolower(id),
    name,
    type,
    resourceGroup,
    location,
    subscriptionId,
    tags
| order by name asc
""".strip()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TagComplianceResult:
    subscription_id: str
    resource_id: str
    resource_name: str
    resource_type: str
    resource_group: str
    location: str
    existing_tags: dict[str, str] = field(default_factory=dict)
    missing_tags: list[str] = field(default_factory=list)
    is_compliant: bool = False
    compliance_pct: float = 0.0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _build_result(
    row: dict[str, Any],
    required_tags: list[str],
) -> TagComplianceResult:
    """Convert a single ARG row into a TagComplianceResult."""
    raw_tags: Any = row.get("tags") or {}
    # ARG may return tags as dict or None
    existing: dict[str, str] = dict(raw_tags) if isinstance(raw_tags, dict) else {}

    # Case-insensitive lookup: build a map keyed by lowercase tag name
    existing_lower: dict[str, str] = {k.lower(): k for k in existing}
    missing: list[str] = [
        tag for tag in required_tags
        if tag.lower() not in existing_lower
    ]

    n_required = len(required_tags)
    n_present = n_required - len(missing)
    pct = (n_present / n_required * 100.0) if n_required else 100.0

    return TagComplianceResult(
        subscription_id=str(row.get("subscriptionId", "")),
        resource_id=str(row.get("id", "")),
        resource_name=str(row.get("name", "")),
        resource_type=str(row.get("type", "")),
        resource_group=str(row.get("resourceGroup", "")),
        location=str(row.get("location", "")),
        existing_tags=existing,
        missing_tags=missing,
        is_compliant=len(missing) == 0,
        compliance_pct=round(pct, 1),
    )


def scan_tagging_compliance(
    credential: Any,
    subscription_ids: list[str],
    required_tags: Optional[list[str]] = None,
) -> list[TagComplianceResult]:
    """ARG scan of all resources. Returns [] on any error (never raises)."""
    tags = required_tags or DEFAULT_REQUIRED_TAGS
    start = time.monotonic()

    if run_arg_query is None:
        logger.warning("tagging_service: arg_helper unavailable — returning empty list")
        return []

    try:
        rows = run_arg_query(credential, subscription_ids, _ARG_KQL)
    except Exception as exc:  # noqa: BLE001
        logger.error("tagging_service: ARG query failed | error=%s", exc)
        return []

    results: list[TagComplianceResult] = []
    for row in rows:
        try:
            results.append(_build_result(row, tags))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tagging_service: skipping malformed row | error=%s", exc)

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "tagging_service: scan complete | resources=%d duration_ms=%d",
        len(results),
        duration_ms,
    )
    return results


def compute_compliance_summary(results: list[TagComplianceResult]) -> dict[str, Any]:
    """Summarise a list of TagComplianceResult into aggregated metrics."""
    total = len(results)
    compliant = sum(1 for r in results if r.is_compliant)
    non_compliant = total - compliant
    pct = round(compliant / total * 100.0, 1) if total else 0.0

    # by_subscription
    by_sub: dict[str, dict[str, Any]] = {}
    for r in results:
        sub = r.subscription_id
        if sub not in by_sub:
            by_sub[sub] = {"total": 0, "compliant": 0, "non_compliant": 0, "compliance_pct": 0.0}
        by_sub[sub]["total"] += 1
        if r.is_compliant:
            by_sub[sub]["compliant"] += 1
        else:
            by_sub[sub]["non_compliant"] += 1
    for sub, s in by_sub.items():
        s["compliance_pct"] = round(s["compliant"] / s["total"] * 100.0, 1) if s["total"] else 0.0

    # by_resource_type
    by_type: dict[str, dict[str, Any]] = {}
    for r in results:
        rt = r.resource_type
        if rt not in by_type:
            by_type[rt] = {"total": 0, "compliant": 0, "non_compliant": 0, "compliance_pct": 0.0}
        by_type[rt]["total"] += 1
        if r.is_compliant:
            by_type[rt]["compliant"] += 1
        else:
            by_type[rt]["non_compliant"] += 1
    for rt, s in by_type.items():
        s["compliance_pct"] = round(s["compliant"] / s["total"] * 100.0, 1) if s["total"] else 0.0

    # missing_tag_frequency
    freq: dict[str, int] = {}
    for r in results:
        for tag in r.missing_tags:
            freq[tag] = freq.get(tag, 0) + 1
    sorted_freq = dict(sorted(freq.items(), key=lambda kv: kv[1], reverse=True))

    return {
        "total": total,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "compliance_pct": pct,
        "by_subscription": by_sub,
        "by_resource_type": by_type,
        "missing_tag_frequency": sorted_freq,
    }


def generate_remediation_script(
    non_compliant: list[TagComplianceResult],
    default_values: Optional[dict[str, str]] = None,
) -> str:
    """Generate an Azure CLI bash script to tag non-compliant resources.

    Groups resources by subscription to minimise az account set calls.
    default_values provides placeholder tag values; falls back to 'PLACEHOLDER'.
    """
    placeholders: dict[str, str] = default_values or {}

    def _placeholder(tag: str) -> str:
        return placeholders.get(tag, "PLACEHOLDER")

    # Group by subscription
    by_sub: dict[str, list[TagComplianceResult]] = {}
    for r in non_compliant:
        by_sub.setdefault(r.subscription_id, []).append(r)

    lines: list[str] = [
        "#!/usr/bin/env bash",
        "# Azure CLI remediation script — Resource Tagging Compliance",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        "# Review placeholder values before executing.",
        "set -euo pipefail",
        "",
    ]

    for sub_id, resources in by_sub.items():
        lines += [
            f"# ── Subscription: {sub_id} ──",
            f"az account set --subscription {sub_id}",
            "",
        ]
        for r in resources:
            if not r.missing_tags:
                continue
            tag_args = " ".join(
                f'"{tag}={_placeholder(tag)}"' for tag in r.missing_tags
            )
            lines += [
                f"# {r.resource_name} ({r.resource_type})",
                f"az tag update \\",
                f"  --resource-id '{r.resource_id}' \\",
                f"  --operation merge \\",
                f"  --tags {tag_args}",
                "",
            ]

    lines.append("echo 'Tagging remediation complete.'")
    return "\n".join(lines) + "\n"
