# EOL Agent

Domain specialist for end-of-life software detection. Discovers OS versions via Azure Resource Graph, software inventory via Log Analytics `ConfigurationData`, and Kubernetes versions via ARG. Checks EOL status against the [endoflife.date API](https://endoflife.date) and the Microsoft Product Lifecycle API, caching results in PostgreSQL (24h TTL) to avoid redundant external calls. Operates in both reactive triage (orchestrator handoff) and proactive estate-scan modes.

## Responsibilities
- Query endoflife.date API and Microsoft Product Lifecycle API for product EOL dates
- Cache EOL lookups in PostgreSQL with a 24-hour TTL (`POSTGRES_DSN`)
- Inventory OS versions, software packages, and Kubernetes versions via ARG and Log Analytics
- Run proactive estate scans to identify all at-risk resources across subscriptions
- Check Activity Log (prior 2h) and Resource Health as pre-triage steps (TRIAGE-002, TRIAGE-003)
- Cite top-3 runbooks via `search_runbooks(domain="eol")` (TRIAGE-005)
- Produce upgrade plans with confidence scores (0.0–1.0); never execute without HITL approval (REMEDI-001)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, `MCPStreamableHTTPTool` mount for Azure MCP Server (`AZURE_MCP_SERVER_URL`), and Foundry registration
- `tools.py` — `@ai_function` tools: endoflife.date client, MS Lifecycle client, PostgreSQL cache helpers, ARG OS/software inventory, proactive estate scan, Activity Log wrapper, Resource Health check, runbook search wrapper
- `requirements.txt` — agent-specific dependencies (`httpx`, `asyncpg`, `azure-mgmt-resourcegraph`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
