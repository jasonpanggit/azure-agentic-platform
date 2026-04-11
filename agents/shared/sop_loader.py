"""SOP loader — per-incident SOP selection from PostgreSQL metadata table.

Selects the most relevant SOP for an incident using a two-layer lookup:
1. Fast PostgreSQL metadata query (domain + resource_type + tag overlap)
2. If no specific match, falls back to the generic SOP for the domain

The agent then uses its FileSearchTool to retrieve the full SOP content
from the Foundry vector store. No blob storage or direct file reads here.

Usage (in each agent's incident handler):
    from shared.sop_loader import select_sop_for_incident
    sop = await select_sop_for_incident(incident, domain="compute", pg_conn=conn)
    # inject sop.grounding_instruction into the Responses API call
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SopLoadResult:
    """Result of a SOP selection for an incident."""

    title: str
    version: str
    foundry_filename: str
    is_generic: bool
    grounding_instruction: str


def _extract_incident_tags(incident: dict[str, Any]) -> list[str]:
    """Extract keyword tags from the incident for SOP tag overlap matching.

    Splits alert_title into lowercase words, filters stop words and
    short tokens. Returns a list of candidate tags.

    Args:
        incident: Incident dict with at least 'alert_title' key.

    Returns:
        List of lowercase keyword strings.
    """
    stop_words = {"the", "a", "an", "is", "on", "in", "at", "of", "and", "or", "for"}
    title = incident.get("alert_title", "")
    resource_type = incident.get("resource_type", "")

    words = re.findall(r"[a-zA-Z]+", title.lower())
    tags = [w for w in words if w not in stop_words and len(w) > 2]

    if resource_type:
        type_fragment = resource_type.split("/")[-1].lower()
        tags.append(type_fragment)

    return list(set(tags))


async def select_sop_for_incident(
    incident: dict[str, Any],
    domain: str,
    pg_conn: Any,
) -> SopLoadResult:
    """Select the best SOP for an incident from the PostgreSQL metadata table.

    Selection priority:
    1. Scenario-specific SOP: domain match + resource_type match + highest tag overlap
    2. Generic domain SOP: domain match + is_generic=TRUE

    The selected SOP's grounding_instruction tells the agent to retrieve
    the full content via its FileSearchTool (file_search tool call).

    Args:
        incident: Incident dict with keys: incident_id, alert_title, resource_type.
        domain: Agent domain name (e.g. "compute", "patch", "arc").
        pg_conn: Active asyncpg connection to the platform PostgreSQL database.

    Returns:
        SopLoadResult with grounding_instruction ready for injection.

    Raises:
        ValueError: If no SOP (specific or generic) is found for the domain.
    """
    incident_tags = _extract_incident_tags(incident)
    resource_type = incident.get("resource_type", "")

    # 1. Try to find scenario-specific SOP by domain + resource_type + tag overlap
    row = await pg_conn.fetchrow(
        """SELECT foundry_filename, title, version, is_generic,
                  array_length(
                    ARRAY(SELECT unnest(scenario_tags) INTERSECT SELECT unnest($3::text[])),
                    1
                  ) AS tag_overlap
           FROM sops
           WHERE domain = $1
             AND is_generic = FALSE
             AND ($2 = ANY(resource_types) OR resource_types IS NULL)
           ORDER BY tag_overlap DESC NULLS LAST,
                    array_length(scenario_tags, 1) DESC NULLS LAST
           LIMIT 1""",
        domain,
        resource_type,
        incident_tags,
    )

    if row is None:
        logger.info(
            "No scenario-specific SOP for domain=%s resource_type=%s; falling back to generic",
            domain,
            resource_type,
        )
        row = await pg_conn.fetchrow(
            "SELECT foundry_filename, title, version, is_generic "
            "FROM sops WHERE domain = $1 AND is_generic = TRUE LIMIT 1",
            domain,
        )

    if row is None:
        raise ValueError(
            f"No SOP found for domain '{domain}'. "
            "Run scripts/upload_sops.py to populate the SOP library."
        )

    filename: str = row["foundry_filename"]
    is_generic: bool = row["is_generic"]
    title: str = row["title"]
    version: str = row["version"]

    logger.info(
        "Selected SOP '%s' (v%s, generic=%s) for incident %s",
        filename,
        version,
        is_generic,
        incident.get("incident_id", "?"),
    )

    grounding = _build_grounding_instruction(
        filename=filename,
        title=title,
        version=version,
        is_generic=is_generic,
    )

    return SopLoadResult(
        title=title,
        version=version,
        foundry_filename=filename,
        is_generic=is_generic,
        grounding_instruction=grounding,
    )


def _build_grounding_instruction(
    filename: str,
    title: str,
    version: str,
    is_generic: bool,
) -> str:
    """Build the grounding instruction string injected into the agent run.

    The instruction tells the agent:
    1. Which SOP file to retrieve via file_search
    2. To follow the SOP steps strictly
    3. That every [REMEDIATION] step requires an ApprovalRecord
    4. That every [NOTIFY] step requires calling sop_notify
    """
    generic_note = (
        "\n[GENERIC FALLBACK -- no scenario-specific SOP matched for this incident]"
        if is_generic
        else ""
    )

    return (
        f"\n## Active SOP: {title} (v{version}){generic_note}\n\n"
        f"Use the `file_search` tool to retrieve the full SOP content for file: **{filename}**\n"
        "Follow every step in that SOP as your primary guide for this incident.\n\n"
        "Rules you MUST follow:\n"
        "- Every [REMEDIATION] step REQUIRES human approval -- call `propose_*` tool, never execute directly.\n"
        "  The propose_* tool creates an ApprovalRecord. Do NOT make any ARM API calls without one.\n"
        '- Every [NOTIFY] step REQUIRES calling the `sop_notify` tool with channels=["teams","email"].\n'
        "- Log any step you skip with explicit justification in your response.\n"
        "- Complete all [DIAGNOSTIC] steps before forming a diagnosis.\n"
    )
