"""Arc Agent — Azure Arc resource specialist stub (Phase 2).

PHASE 2 STATUS: STUB

The Arc Agent is provisioned with a system-assigned managed identity and Container App
in Phase 2, but all Arc-specific tooling requires the custom Arc MCP Server which is
not available until Phase 3.

In Phase 2, this agent returns a structured stub response for all incidents, directing
operators to the SRE Agent for general Azure Monitor-based monitoring of Arc resources.

Safety constraints:
    - MUST NOT attempt to query Arc resources using Azure MCP Server (Arc coverage gap confirmed).
    - MUST NOT call Arc MCP Server tools in Phase 2 — the server does not exist yet.
    - MUST clearly communicate stub status: every response includes "phase_available": 3.
    - MUST recommend SRE Agent as the Phase 2 escalation path.
    - MUST NOT use wildcard tool permissions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework import ChatAgent, ai_function

from agents.shared.auth import get_foundry_client
from agents.shared.otel import setup_telemetry

tracer = setup_telemetry("aiops-arc-agent")

# ---------------------------------------------------------------------------
# Phase 2: No MCP tools permitted — Arc MCP Server not available until Phase 3.
# ---------------------------------------------------------------------------

ALLOWED_MCP_TOOLS: list[str] = []

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

ARC_AGENT_SYSTEM_PROMPT = """You are the AAP Arc Agent.

## Phase 2 Status: STUB

Arc-specific capabilities are NOT yet available in Phase 2. The custom Arc MCP Server
required for Arc server, Arc Kubernetes, and Arc data service tooling will be built
in Phase 3.

For every incident you receive, you MUST:
1. Immediately return the Phase 2 stub response via `handle_arc_incident`.
2. Clearly communicate that Arc capabilities are pending Phase 3.
3. Recommend escalation to the SRE Agent for general Azure Monitor-based monitoring.
4. Include "phase_available": 3 in every response.

## What NOT to do in Phase 2

- Do NOT attempt to query Arc resources via Azure MCP Server (confirmed coverage gap).
- Do NOT attempt to call Arc MCP Server tools — the server does not exist yet.
- Do NOT attempt Activity Log queries, Resource Health queries, or any Azure API calls
  for Arc resources without the Arc MCP Server.

## Allowed Tools

- `handle_arc_incident` (stub response only)

No MCP tools are permitted in Phase 2.
"""


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


@ai_function
def handle_arc_incident(incident: Dict[str, Any]) -> Dict[str, Any]:
    """Return the Phase 2 structured stub response for all Arc incidents.

    In Phase 2, the Arc MCP Server is not available. This function returns
    a structured response acknowledging the pending Phase 3 capabilities and
    directing operators to the SRE Agent for general monitoring.

    Phase 3 will replace this stub with full Arc diagnostic tooling:
    arc_servers_list, arc_servers_get, arc_k8s_list, arc_k8s_get,
    arc_extensions_list, arc_data_services_list.

    Args:
        incident: Incident dict from the Orchestrator handoff payload.
            Expected keys: incident_id, correlation_id, affected_resources,
            detection_rule.

    Returns:
        Structured stub response with status="pending_phase3",
        phase_available=3, needs_cross_domain=True, suspected_domain="sre".
    """
    incident_id = incident.get("incident_id", "unknown")

    return {
        "status": "pending_phase3",
        "message": (
            "Arc-specific capabilities are pending Phase 3 implementation. "
            "Please triage Arc incidents manually until Phase 3 is complete."
        ),
        "incident_id": incident_id,
        "recommendation": "Escalate to SRE agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # Phase 3 details for operator awareness
        "phase_available": 3,
        "agent": "arc-agent",
        "needs_cross_domain": True,
        "suspected_domain": "sre",
    }


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_arc_agent() -> ChatAgent:
    """Create and configure the Arc ChatAgent stub instance.

    Returns:
        ChatAgent configured with stub tools and Phase 2 system prompt.
    """
    client = get_foundry_client()

    return ChatAgent(
        name="arc-agent",
        description=(
            "Azure Arc domain specialist — Phase 2 stub; "
            "full Arc capabilities available in Phase 3."
        ),
        system_prompt=ARC_AGENT_SYSTEM_PROMPT,
        client=client,
        tools=[handle_arc_incident],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = create_arc_agent()
    agent.serve()
