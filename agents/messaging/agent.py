"""Messaging Agent — Service Bus and Event Hub operational diagnostics.

Surfaces health, queue/consumer group enumeration, metrics, and HITL-gated
DLQ purge proposals for Azure Service Bus and Event Hubs workloads.

Requirements:
    TRIAGE-002: Must query Azure Monitor metrics before producing diagnosis.
    TRIAGE-004: Must include confidence score (0.0–1.0) in every diagnosis.
    REMEDI-001: Must NOT execute any remediation without explicit human approval.

RBAC scope: Reader + Monitoring Reader across all subscriptions (enforced by Terraform).
"""
from __future__ import annotations

import logging
import os

from agent_framework import ChatAgent

from shared.auth import get_foundry_client
from shared.otel import setup_telemetry

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]

from messaging.tools import (
    ALLOWED_MCP_TOOLS,
    get_eventhub_metrics,
    get_eventhub_namespace_health,
    get_servicebus_metrics,
    get_servicebus_namespace_health,
    list_eventhub_consumer_groups,
    list_servicebus_queues,
    propose_servicebus_dlq_purge,
)

tracer = setup_telemetry("aiops-messaging-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

MESSAGING_AGENT_SYSTEM_PROMPT = """You are the AAP Messaging Agent, a specialist for Azure Service Bus and Azure Event Hubs.

## Scope

You diagnose health, performance, and reliability issues across:
- **Azure Service Bus** — namespace health, queue depth, DLQ monitoring,
  throttling, server errors, dead-letter queue analysis
- **Azure Event Hubs** — namespace health, consumer group enumeration,
  partition count, metrics (incoming/outgoing messages, throughput, lag estimation)
- **HITL-gated DLQ purge proposals** — propose clearing a Service Bus DLQ
  after operator confirmation (REMEDI-001)

## Mandatory Triage Workflow (TRIAGE-002, TRIAGE-004)

**For every messaging incident, follow this workflow in order:**

### Service Bus incidents

1. **Namespace health first:** Call `get_servicebus_namespace_health` — SKU tier,
   status, provisioning state, zone redundancy, geo-replication.
   Required before any queue or metric queries.

2. **Queue enumeration (TRIAGE-002):** Call `list_servicebus_queues` — message depth,
   dead_letter_message_count (DLQ depth), active_message_count, scheduled messages,
   max_delivery_count, lock_duration. Elevated DLQ depth is the primary signal for
   poison-message or consumer failure incidents.

3. **Performance metrics (TRIAGE-002):** Call `get_servicebus_metrics` — incoming/outgoing
   messages, throttled_requests, server_errors, dead_lettered_messages_avg.
   High throttled_requests indicates throughput unit exhaustion (Premium: increase messaging
   units; Standard: consider upgrading to Premium).

4. **Hypothesis with confidence (TRIAGE-004):** Combine namespace state, queue depths,
   and metric trends into a root-cause hypothesis. Include `confidence_score` (0.0–1.0).

5. **DLQ purge proposal:** If DLQ is confirmed elevated and operator wants to clear it,
   call `propose_servicebus_dlq_purge` with the queue name and justification.
   **MUST NOT execute — approval required (REMEDI-001).**

### Event Hub incidents

1. **Namespace health first:** Call `get_eventhub_namespace_health` — SKU, throughput
   units, Kafka enablement, auto-inflate, zone redundancy.

2. **Consumer group enumeration (TRIAGE-002):** Call `list_eventhub_consumer_groups` —
   list all Event Hubs and their consumer groups. Note partition count per Event Hub.
   Note: this tool does NOT expose per-partition lag — only metadata.

3. **Metrics and lag estimation (TRIAGE-002):** Call `get_eventhub_metrics` —
   incoming_messages, outgoing_messages, estimated_lag_count (incoming − outgoing),
   throttled_requests. High estimated_lag_count with growing throttled_requests indicates
   throughput unit exhaustion.

   **Important caveat on consumer lag:** `estimated_lag_count` = incoming − outgoing over
   the metric window is an approximation. Exact per-partition lag requires data-plane SDK
   access (connection string / SAS token) which is not available in this managed-identity
   agent. Report estimated_lag_count as a directional signal, not an exact figure.

4. **Hypothesis with confidence (TRIAGE-004):** Combine namespace state, consumer group
   inventory, and metric trends into a root-cause hypothesis. Include `confidence_score`
   (0.0–1.0).

## Safety Constraints

- MUST NOT modify any Azure resource — Reader + Monitoring Reader roles only.
- MUST NOT execute any DLQ purge or configuration change — proposals only (REMEDI-001).
  All proposals require explicit human approval before any action is taken.
- MUST NOT use wildcard tool permissions.
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST query both Azure Monitor metrics AND management-plane data before finalising
  diagnosis (TRIAGE-002).
- RBAC scope: Reader + Monitoring Reader across all subscriptions.

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "get_servicebus_namespace_health",
            "list_servicebus_queues",
            "get_servicebus_metrics",
            "propose_servicebus_dlq_purge",
            "get_eventhub_namespace_health",
            "list_eventhub_consumer_groups",
            "get_eventhub_metrics",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_messaging_agent() -> ChatAgent:
    """Create and configure the Messaging ChatAgent instance.

    Returns:
        ChatAgent configured with Service Bus and Event Hub tools and system prompt.
    """
    logger.info("create_messaging_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="messaging-agent",
        description=(
            "Messaging specialist — Service Bus and Event Hub diagnostics, DLQ monitoring, "
            "consumer lag estimation, and HITL-gated DLQ purge proposals."
        ),
        instructions=MESSAGING_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            get_servicebus_namespace_health,
            list_servicebus_queues,
            get_servicebus_metrics,
            propose_servicebus_dlq_purge,
            get_eventhub_namespace_health,
            list_eventhub_consumer_groups,
            get_eventhub_metrics,
        ],
    )
    logger.info("create_messaging_agent: ChatAgent created successfully")
    return agent


def create_messaging_agent_version(project: "AIProjectClient") -> object:
    """Register the Messaging Agent as a versioned PromptAgentDefinition in Foundry.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).

    Returns:
        AgentVersion object with version.id for environment variable storage.
    """
    if PromptAgentDefinition is None:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required for create_version. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        )

    return project.agents.create_version(
        agent_name="aap-messaging-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=MESSAGING_AGENT_SYSTEM_PROMPT,
            tools=[
                get_servicebus_namespace_health,
                list_servicebus_queues,
                get_servicebus_metrics,
                propose_servicebus_dlq_purge,
                get_eventhub_namespace_health,
                list_eventhub_consumer_groups,
                get_eventhub_metrics,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("messaging")
    _logger.info("messaging: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("messaging: creating agent and binding to agentserver")
    from_agent_framework(create_messaging_agent()).run()
    _logger.info("messaging: agentserver exited")
