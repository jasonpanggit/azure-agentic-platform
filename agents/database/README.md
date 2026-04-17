# Database Agent

Domain specialist for the three primary database engines used across the platform estate: Azure Cosmos DB, PostgreSQL Flexible Server, and Azure SQL. Correlates Azure Monitor metrics with diagnostic logs to diagnose performance, availability, and compliance issues, proposing fixes only through the HITL approval flow.

## Responsibilities
- List and inspect Cosmos DB accounts, PostgreSQL Flexible Servers, and Azure SQL servers/databases
- Query Azure Monitor metrics: RU consumption, DTUs, CPU, storage, connection counts, replication lag
- Retrieve slow-query logs, error logs, and audit logs from Log Analytics
- Detect throttling events and capacity saturation across all three database types
- Propose (but never execute) scaling, failover, or configuration changes; gated by HITL approval (REMEDI-001)
- Produce diagnoses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`cosmos`, `postgres`, `sql`, `monitor`), and Foundry registration
- `tools.py` — `@ai_function` tools: Cosmos DB list/get, PostgreSQL list/get, SQL list/get, metrics query, log query
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-cosmosdb`, `azure-mgmt-rdbms`, `azure-mgmt-sql`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
