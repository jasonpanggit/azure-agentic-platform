from __future__ import annotations
"""Operator Shift Handover Report — Phase 74.

Generates an 8-hour shift briefing: open incidents, resolved, SLO status,
top patterns, pending approvals, and recommended focus areas.

Entry point: generate_handover_report(cosmos_client, cosmos_database_name, shift_hours)
"""
import os

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class HandoverReport:
    report_id: str
    shift_start: str           # ISO-8601
    shift_end: str             # ISO-8601
    generated_at: str
    # Incident stats
    open_incidents: int
    resolved_this_shift: int
    new_this_shift: int
    sev0_open: int
    sev1_open: int
    # Top open incidents (list of dicts: incident_id, title, severity, status, age_hours)
    top_open_incidents: list[dict]
    # SLO status
    slo_status: str            # "healthy" | "at_risk" | "breached" | "unknown"
    slo_burn_rate: Optional[float]
    # Patterns
    top_patterns: list[dict]   # [{pattern_id, description, frequency, last_seen}]
    # Approvals
    pending_approvals: int
    urgent_approvals: list[dict]
    # Recommended focus
    recommended_focus: list[str]
    # Markdown for download
    markdown: str


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANK: Dict[str, int] = {"Sev0": 0, "Sev1": 1, "Sev2": 2, "Sev3": 3}
_CLOSED_STATUSES = {"resolved", "dismissed", "closed"}


def _severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, 99)


def _is_open(doc: Dict[str, Any]) -> bool:
    status = (doc.get("status") or "").lower()
    return status not in _CLOSED_STATUSES


def _age_hours(detected_at: Optional[str], now: datetime) -> float:
    if not detected_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        return max(0.0, (now - dt).total_seconds() / 3600)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Cosmos helpers
# ---------------------------------------------------------------------------


def _query_container(
    cosmos_client: Any,
    database_name: str,
    container_name: str,
    query: str,
    parameters: Optional[list] = None,
) -> List[Dict[str, Any]]:
    """Query a Cosmos container. Returns empty list on any error."""
    try:
        db = cosmos_client.get_database_client(database_name)
        container = db.get_container_client(container_name)
        kwargs: Dict[str, Any] = {"enable_cross_partition_query": True}
        if parameters:
            kwargs["parameters"] = parameters
        return list(container.query_items(query=query, **kwargs))
    except Exception as exc:
        logger.warning("Cosmos query failed (%s / %s): %s", database_name, container_name, exc)
        return []


def _upsert_document(
    cosmos_client: Any,
    database_name: str,
    container_name: str,
    doc: Dict[str, Any],
) -> None:
    """Upsert a document. Silently ignores errors."""
    try:
        db = cosmos_client.get_database_client(database_name)
        container = db.get_container_client(container_name)
        container.upsert_item(doc)
    except Exception as exc:
        logger.warning("Cosmos upsert failed (%s / %s): %s", database_name, container_name, exc)


# ---------------------------------------------------------------------------
# SLO helpers
# ---------------------------------------------------------------------------


def _derive_slo_status(cosmos_client: Any, database_name: str) -> tuple[str, Optional[float]]:
    """Get SLO burn rate from Cosmos slo_metrics. Returns (status, burn_rate)."""
    try:
        rows = _query_container(
            cosmos_client,
            database_name,
            "slo_metrics",
            "SELECT TOP 1 c.burn_rate_1h, c.error_budget_pct FROM c ORDER BY c._ts DESC",
        )
        if not rows:
            return "unknown", None
        row = rows[0]
        burn_rate = row.get("burn_rate_1h")
        budget_pct = row.get("error_budget_pct")
        if budget_pct is not None and float(budget_pct) <= 0.0:
            return "breached", burn_rate
        if burn_rate is not None and float(burn_rate) > 2.0:
            return "at_risk", burn_rate
        return "healthy", burn_rate
    except Exception as exc:
        logger.warning("SLO status derivation failed: %s", exc)
        return "unknown", None


# ---------------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------------


def _get_top_patterns(cosmos_client: Any, database_name: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Fetch top patterns from Cosmos pattern_analysis container."""
    try:
        rows = _query_container(
            cosmos_client,
            database_name,
            "pattern_analysis",
            "SELECT TOP 1 c.top_patterns, c.analyzed_at FROM c ORDER BY c._ts DESC",
        )
        if not rows:
            return []
        top = rows[0].get("top_patterns") or []
        analyzed_at = rows[0].get("analyzed_at", "")
        result = []
        for p in top[:limit]:
            result.append({
                "pattern_id": p.get("pattern_id") or p.get("id") or "",
                "description": (
                    p.get("description")
                    or f"{p.get('domain', '')} / {p.get('resource_type', '')} / {p.get('detection_rule', '')}"
                ).strip(" /"),
                "frequency": p.get("frequency_per_week") or p.get("incident_count") or 0,
                "last_seen": p.get("last_seen") or analyzed_at,
            })
        return result
    except Exception as exc:
        logger.warning("Pattern fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Focus derivation
# ---------------------------------------------------------------------------


def _build_focus(
    sev0_open: int,
    sev1_open: int,
    pending_approvals: int,
    top_patterns: List[Dict[str, Any]],
    slo_status: str,
) -> List[str]:
    items: List[str] = []
    if sev0_open > 0:
        items.append(f"🚨 Immediate: resolve {sev0_open} open Sev0 incident(s)")
    if sev1_open > 0:
        items.append(f"⚠️  High priority: address {sev1_open} open Sev1 incident(s)")
    if slo_status == "breached":
        items.append("🔴 SLO breached — error budget exhausted; escalate immediately")
    elif slo_status == "at_risk":
        items.append("🟡 SLO at risk — elevated burn rate detected; monitor closely")
    if pending_approvals > 0:
        items.append(f"✋ Review {pending_approvals} pending HITL approval(s)")
    for p in top_patterns[:2]:
        desc = p.get("description", "")
        freq = p.get("frequency", 0)
        if desc:
            items.append(f"🔁 Recurring pattern: '{desc}' (freq: {freq}/wk) — consider runbook automation")
    if not items:
        items.append("✅ No critical items — maintain normal monitoring cadence")
    return items


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(report: HandoverReport) -> str:
    """Render HandoverReport as a clean markdown string."""
    lines: List[str] = []

    lines.append(f"# Operator Shift Handover Report")
    lines.append(f"")
    lines.append(f"**Shift:** {report.shift_start} → {report.shift_end} UTC")
    lines.append(f"**Generated:** {report.generated_at}")
    lines.append(f"**Report ID:** `{report.report_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Stats
    lines.append("## Incident Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Open incidents | {report.open_incidents} |")
    lines.append(f"| Resolved this shift | {report.resolved_this_shift} |")
    lines.append(f"| New this shift | {report.new_this_shift} |")
    lines.append(f"| Sev0 open | {report.sev0_open} |")
    lines.append(f"| Sev1 open | {report.sev1_open} |")
    lines.append("")

    # SLO
    lines.append("## SLO Status")
    lines.append("")
    burn = f"{report.slo_burn_rate:.2f}" if report.slo_burn_rate is not None else "N/A"
    lines.append(f"- **Status:** {report.slo_status}")
    lines.append(f"- **Burn rate (1h):** {burn}")
    lines.append("")

    # Top open incidents
    if report.top_open_incidents:
        lines.append("## Top Open Incidents")
        lines.append("")
        lines.append("| ID | Title | Severity | Status | Age (h) |")
        lines.append("|----|-------|----------|--------|---------|")
        for inc in report.top_open_incidents:
            lines.append(
                f"| `{inc.get('incident_id', '')}` "
                f"| {inc.get('title', 'N/A')} "
                f"| {inc.get('severity', '')} "
                f"| {inc.get('status', '')} "
                f"| {inc.get('age_hours', 0):.1f} |"
            )
        lines.append("")

    # Patterns
    if report.top_patterns:
        lines.append("## Recurring Patterns")
        lines.append("")
        for p in report.top_patterns:
            lines.append(f"- **{p.get('description', '')}** — freq: {p.get('frequency', 0)}/wk, last seen: {p.get('last_seen', 'N/A')}")
        lines.append("")

    # Approvals
    lines.append("## Pending Approvals")
    lines.append("")
    lines.append(f"- **Total pending:** {report.pending_approvals}")
    if report.urgent_approvals:
        lines.append(f"- **Urgent (Sev0/Sev1):** {len(report.urgent_approvals)}")
        for a in report.urgent_approvals[:3]:
            lines.append(f"  - `{a.get('approval_id', '')}` — {a.get('title', '')} ({a.get('severity', '')})")
    lines.append("")

    # Focus
    lines.append("## Recommended Focus")
    lines.append("")
    for item in report.recommended_focus:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by Azure Agentic Platform — Operator Shift Handover*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adaptive Card for Teams
# ---------------------------------------------------------------------------


def render_teams_card(report: HandoverReport) -> dict:
    """Render HandoverReport as a Teams Adaptive Card dict."""
    slo_color_map = {
        "healthy": "Good",
        "at_risk": "Warning",
        "breached": "Attention",
        "unknown": "Default",
    }
    slo_color = slo_color_map.get(report.slo_status, "Default")

    facts = [
        {"title": "Open Incidents", "value": str(report.open_incidents)},
        {"title": "Resolved This Shift", "value": str(report.resolved_this_shift)},
        {"title": "New This Shift", "value": str(report.new_this_shift)},
        {"title": "Pending Approvals", "value": str(report.pending_approvals)},
        {"title": "SLO Status", "value": report.slo_status.upper()},
    ]

    incident_rows = []
    for inc in report.top_open_incidents[:3]:
        incident_rows.append({
            "type": "TextBlock",
            "text": f"• [{inc.get('severity', '')}] {inc.get('title', 'N/A')} ({inc.get('age_hours', 0):.1f}h)",
            "wrap": True,
            "size": "Small",
        })

    body = [
        {
            "type": "TextBlock",
            "text": "🔄 Operator Shift Handover",
            "weight": "Bolder",
            "size": "Medium",
        },
        {
            "type": "TextBlock",
            "text": f"Shift: {report.shift_start[:16]} → {report.shift_end[:16]} UTC",
            "size": "Small",
            "isSubtle": True,
        },
        {"type": "FactSet", "facts": facts},
    ]

    if incident_rows:
        body.append({"type": "TextBlock", "text": "**Top Open Incidents**", "weight": "Bolder", "size": "Small"})
        body.extend(incident_rows)

    if report.recommended_focus:
        body.append({"type": "TextBlock", "text": "**Recommended Focus**", "weight": "Bolder", "size": "Small"})
        body.append({
            "type": "TextBlock",
            "text": "\n".join(f"• {f}" for f in report.recommended_focus[:3]),
            "wrap": True,
            "size": "Small",
        })

    platform_url = "https://aap.example.com"  # overridden by env if needed
    import os
    platform_url = os.environ.get("PLATFORM_URL", platform_url)

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Open Platform",
                "url": platform_url,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------


async def generate_handover_report(
    cosmos_client: Any,
    cosmos_database_name: str,
    shift_hours: int = 8,
) -> HandoverReport:
    """Generate a shift handover report. Never raises — partial data returned on error."""
    start_time = time.monotonic()
    now = datetime.now(timezone.utc)
    shift_end = now
    shift_start = now - timedelta(hours=shift_hours)
    shift_start_iso = shift_start.isoformat()
    shift_end_iso = shift_end.isoformat()
    report_id = f"handover-{uuid.uuid4().hex[:8]}"
    generated_at = now.isoformat()

    # ---- Defaults ----
    open_incidents = 0
    resolved_this_shift = 0
    new_this_shift = 0
    sev0_open = 0
    sev1_open = 0
    top_open_incidents: List[Dict[str, Any]] = []
    slo_status = "unknown"
    slo_burn_rate: Optional[float] = None
    top_patterns: List[Dict[str, Any]] = []
    pending_approvals = 0
    urgent_approvals: List[Dict[str, Any]] = []

    try:
        # ---- Open incidents ----
        all_incidents = _query_container(
            cosmos_client,
            cosmos_database_name,
            "incidents",
            "SELECT c.id, c.incident_id, c.title, c.severity, c.status, c.detected_at, c.resolved_at "
            "FROM c",
        )

        open_docs = [d for d in all_incidents if _is_open(d)]
        open_incidents = len(open_docs)

        resolved_docs = [
            d for d in all_incidents
            if (d.get("status") or "").lower() == "resolved"
            and (d.get("resolved_at") or "") >= shift_start_iso
        ]
        resolved_this_shift = len(resolved_docs)

        new_docs = [
            d for d in all_incidents
            if (d.get("detected_at") or "") >= shift_start_iso
        ]
        new_this_shift = len(new_docs)

        sev0_open = sum(1 for d in open_docs if (d.get("severity") or "") == "Sev0")
        sev1_open = sum(1 for d in open_docs if (d.get("severity") or "") == "Sev1")

        # Top 5 open sorted by severity
        sorted_open = sorted(open_docs, key=lambda d: _severity_rank(d.get("severity") or ""))
        for doc in sorted_open[:5]:
            top_open_incidents.append({
                "incident_id": doc.get("incident_id") or doc.get("id") or "",
                "title": doc.get("title") or "Untitled",
                "severity": doc.get("severity") or "Unknown",
                "status": doc.get("status") or "open",
                "age_hours": round(_age_hours(doc.get("detected_at"), now), 1),
            })

    except Exception as exc:
        logger.warning("Incident query failed: %s", exc)

    try:
        # ---- Pending approvals ----
        approval_docs = _query_container(
            cosmos_client,
            cosmos_database_name,
            "approvals",
            "SELECT c.id, c.approval_id, c.title, c.severity, c.status FROM c "
            "WHERE c.status = 'pending'",
        )
        pending_approvals = len(approval_docs)
        urgent_approvals = [
            {
                "approval_id": d.get("approval_id") or d.get("id") or "",
                "title": d.get("title") or "Untitled",
                "severity": d.get("severity") or "",
            }
            for d in approval_docs
            if (d.get("severity") or "") in ("Sev0", "Sev1")
        ]

    except Exception as exc:
        logger.warning("Approvals query failed: %s", exc)

    try:
        slo_status, slo_burn_rate = _derive_slo_status(cosmos_client, cosmos_database_name)
    except Exception as exc:
        logger.warning("SLO status failed: %s", exc)

    try:
        top_patterns = _get_top_patterns(cosmos_client, cosmos_database_name)
    except Exception as exc:
        logger.warning("Pattern fetch failed: %s", exc)

    recommended_focus = _build_focus(
        sev0_open, sev1_open, pending_approvals, top_patterns, slo_status
    )

    markdown = render_markdown(HandoverReport(
        report_id=report_id,
        shift_start=shift_start_iso,
        shift_end=shift_end_iso,
        generated_at=generated_at,
        open_incidents=open_incidents,
        resolved_this_shift=resolved_this_shift,
        new_this_shift=new_this_shift,
        sev0_open=sev0_open,
        sev1_open=sev1_open,
        top_open_incidents=top_open_incidents,
        slo_status=slo_status,
        slo_burn_rate=slo_burn_rate,
        top_patterns=top_patterns,
        pending_approvals=pending_approvals,
        urgent_approvals=urgent_approvals,
        recommended_focus=recommended_focus,
        markdown="",  # placeholder for nested call
    ))

    report = HandoverReport(
        report_id=report_id,
        shift_start=shift_start_iso,
        shift_end=shift_end_iso,
        generated_at=generated_at,
        open_incidents=open_incidents,
        resolved_this_shift=resolved_this_shift,
        new_this_shift=new_this_shift,
        sev0_open=sev0_open,
        sev1_open=sev1_open,
        top_open_incidents=top_open_incidents,
        slo_status=slo_status,
        slo_burn_rate=slo_burn_rate,
        top_patterns=top_patterns,
        pending_approvals=pending_approvals,
        urgent_approvals=urgent_approvals,
        recommended_focus=recommended_focus,
        markdown=markdown,
    )

    # Persist to handover_reports container (TTL 24h, set server-side via container policy)
    if cosmos_client is not None:
        try:
            doc: Dict[str, Any] = {
                "id": report_id,
                "report_id": report_id,
                "shift_start": shift_start_iso,
                "shift_end": shift_end_iso,
                "generated_at": generated_at,
                "open_incidents": open_incidents,
                "resolved_this_shift": resolved_this_shift,
                "new_this_shift": new_this_shift,
                "sev0_open": sev0_open,
                "sev1_open": sev1_open,
                "top_open_incidents": top_open_incidents,
                "slo_status": slo_status,
                "slo_burn_rate": slo_burn_rate,
                "top_patterns": top_patterns,
                "pending_approvals": pending_approvals,
                "urgent_approvals": urgent_approvals,
                "recommended_focus": recommended_focus,
                "markdown": markdown,
                "ttl": 86400,
            }
            _upsert_document(cosmos_client, cosmos_database_name, "handover_reports", doc)
        except Exception as exc:
            logger.warning("Failed to persist handover report: %s", exc)

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "Handover report generated: report_id=%s open=%d resolved=%d duration_ms=%.0f",
        report_id,
        open_incidents,
        resolved_this_shift,
        duration_ms,
    )
    return report
