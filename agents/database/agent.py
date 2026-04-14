"""Database Agent — Cosmos DB, PostgreSQL Flexible Server, and Azure SQL diagnostics.

Surfaces health, performance, and compliance diagnostics across the three primary
database engines used in the platform estate and by monitored workloads.

Requirements:
    TRIAGE-002: Must query Azure Monitor metrics AND diagnostic logs before producing diagnosis.
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

from database.tools import (
    ALLOWED_MCP_TOOLS,
    get_cosmos_account_health,
    get_cosmos_throughput_metrics,
    get_postgres_metrics,
    get_postgres_server_health,
    get_sql_database_health,
    get_sql_dtu_metrics,
    propose_cosmos_throughput_scale,
    propose_postgres_sku_scale,
    propose_sql_elastic_pool_move,
    query_cosmos_diagnostic_logs,
    query_postgres_slow_queries,
    query_sql_query_store,
)

tracer = setup_telemetry("aiops-database-agent")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

DATABASE_AGENT_SYSTEM_PROMPT = """You are the AAP Database Agent, a specialist for Azure database
infrastructure covering Cosmos DB, PostgreSQL Flexible Server, and Azure SQL Database.

## Scope

You diagnose health, performance, and compliance issues across:
- **Azure Cosmos DB** — request unit (RU) throttling, hot partition detection, latency analysis
- **PostgreSQL Flexible Server** — resource utilisation, slow queries, HA state, replication
- **Azure SQL Database** — DTU/vCore utilisation, deadlocks, query store analysis, elastic pools

## Mandatory Triage Workflow (TRIAGE-002, TRIAGE-004)

**For every database incident, follow this workflow in order:**

### Cosmos DB incidents

1. **Account health first:** Call `get_cosmos_account_health` — provisioning state, regions,
   backup policy, consistency level. Required before any metric queries.

2. **Throughput metrics (TRIAGE-002):** Call `get_cosmos_throughput_metrics` — surface
   NormalizedRUConsumption, Http429s, and ServerSideLatency. A NormalizedRUConsumption
   above 80% or any Http429s indicates throughput pressure.

3. **Diagnostic logs:** Call `query_cosmos_diagnostic_logs` — identify hot partition keys,
   operations with status 429, and high-latency operations via Log Analytics.

4. **Hypothesis with confidence (TRIAGE-004):** Combine ARM state, metrics, and logs into
   a root-cause hypothesis. Include `confidence_score` (0.0–1.0).

5. **Throughput proposal:** If RU pressure is confirmed, call `propose_cosmos_throughput_scale`
   with a justification. **MUST NOT execute — approval required (REMEDI-001).**

### PostgreSQL incidents

1. **Server health first:** Call `get_postgres_server_health` — server state, HA, replication
   role, SKU, storage.

2. **Performance metrics (TRIAGE-002):** Call `get_postgres_metrics` — cpu_percent,
   memory_percent, connections_failed. Required before log queries.

3. **Slow query logs:** Call `query_postgres_slow_queries` — identify long-running queries
   via Log Analytics (threshold_ms default 1000ms).

4. **Hypothesis with confidence (TRIAGE-004):** Combine ARM, metrics, logs into hypothesis.

5. **SKU proposal:** If resource exhaustion is confirmed, call `propose_postgres_sku_scale`.
   **MUST NOT execute — approval required (REMEDI-001).**

### Azure SQL incidents

1. **Database health first:** Call `get_sql_database_health` — status, service tier, zone
   redundancy, elastic pool membership.

2. **DTU/vCore metrics (TRIAGE-002):** Call `get_sql_dtu_metrics` — dtu_consumption_percent,
   deadlock count, sessions_percent. Required before log queries.

3. **Query store:** Call `query_sql_query_store` — top slow queries by average duration
   via Log Analytics.

4. **Hypothesis with confidence (TRIAGE-004):** Combine ARM, metrics, logs into hypothesis.

5. **Elastic pool proposal:** If sustained DTU pressure is confirmed, call
   `propose_sql_elastic_pool_move`. **MUST NOT execute — approval required (REMEDI-001).**

## Safety Constraints

- MUST NOT modify any Azure database resource — Reader + Monitoring Reader roles only.
- MUST NOT execute any scaling, configuration, or remediation action — proposals only (REMEDI-001).
  All proposals require explicit human approval before any action is taken.
- MUST NOT use wildcard tool permissions.
- MUST include confidence score (0.0–1.0) in every diagnosis (TRIAGE-004).
- MUST query both Azure Monitor metrics AND diagnostic logs before finalising diagnosis (TRIAGE-002).
- RBAC scope: Reader + Monitoring Reader across all subscriptions.

## Allowed Tools

{allowed_tools}
""".format(
    allowed_tools="\n".join(
        f"- `{t}`"
        for t in ALLOWED_MCP_TOOLS
        + [
            "get_cosmos_account_health",
            "get_cosmos_throughput_metrics",
            "query_cosmos_diagnostic_logs",
            "propose_cosmos_throughput_scale",
            "get_postgres_server_health",
            "get_postgres_metrics",
            "query_postgres_slow_queries",
            "propose_postgres_sku_scale",
            "get_sql_database_health",
            "get_sql_dtu_metrics",
            "query_sql_query_store",
            "propose_sql_elastic_pool_move",
        ]
    )
)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def create_database_agent() -> ChatAgent:
    """Create and configure the Database ChatAgent instance.

    Returns:
        ChatAgent configured with database tools and system prompt.
    """
    logger.info("create_database_agent: initialising Foundry client")
    client = get_foundry_client()

    agent = ChatAgent(
        name="database-agent",
        description=(
            "Database specialist — Cosmos DB, PostgreSQL Flexible Server, "
            "and Azure SQL Database health and performance diagnostics."
        ),
        instructions=DATABASE_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            get_cosmos_account_health,
            get_cosmos_throughput_metrics,
            query_cosmos_diagnostic_logs,
            propose_cosmos_throughput_scale,
            get_postgres_server_health,
            get_postgres_metrics,
            query_postgres_slow_queries,
            propose_postgres_sku_scale,
            get_sql_database_health,
            get_sql_dtu_metrics,
            query_sql_query_store,
            propose_sql_elastic_pool_move,
        ],
    )
    logger.info("create_database_agent: ChatAgent created successfully")
    return agent


def create_database_agent_version(project: "AIProjectClient") -> object:
    """Register the Database Agent as a versioned PromptAgentDefinition in Foundry.

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
        agent_name="aap-database-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=DATABASE_AGENT_SYSTEM_PROMPT,
            tools=[
                get_cosmos_account_health,
                get_cosmos_throughput_metrics,
                query_cosmos_diagnostic_logs,
                propose_cosmos_throughput_scale,
                get_postgres_server_health,
                get_postgres_metrics,
                query_postgres_slow_queries,
                propose_postgres_sku_scale,
                get_sql_database_health,
                get_sql_dtu_metrics,
                query_sql_query_store,
                propose_sql_elastic_pool_move,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from shared.logging_config import setup_logging

    _logger = setup_logging("database")
    _logger.info("database: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework

    _logger.info("database: creating agent and binding to agentserver")
    from_agent_framework(create_database_agent()).run()
    _logger.info("database: agentserver exited")
