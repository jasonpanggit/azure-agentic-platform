# Phase 46: Database Agent - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Build a Database domain agent that surfaces health, performance, and compliance diagnostics for Azure Cosmos DB, PostgreSQL Flexible Server, and Azure SQL Database. The agent replaces zero current database-specific tooling with a 12-tool surface covering the three database engines in the platform's own estate and those most commonly used by monitored workloads. Deploys as `ca-database-prod` Container App with orchestrator routing for `domain: database` incidents.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase. Follow the established compute/network/storage/SRE agent pattern exactly:
- `agents/database/` directory mirroring `agents/sre/`, `agents/storage/` structure
- `tools.py` with `@ai_function` decorators, lazy SDK imports, `instrument_tool_call`, never-raise pattern
- `agent.py` with `DATABASE_AGENT_SYSTEM_PROMPT` and `create_database_agent()` factory
- `requirements.txt` pinning azure-mgmt-* SDK versions
- `Dockerfile` following the compute agent pattern (non-root user, linux/amd64)
- `agents/tests/database/` with 50+ unit tests covering success, error, SDK-missing paths
- Orchestrator routing: add `database` to `DOMAIN_AGENT_MAP` in `services/api-gateway/`
- HITL proposals follow the WAL pattern from existing `propose_*` functions in storage/sre agents

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/shared/auth.py` — `get_credential()`, `get_agent_identity()`
- `agents/shared/otel.py` — `instrument_tool_call()`, `setup_telemetry()`
- `agents/sre/tools.py` — reference pattern for lazy SDK imports and never-raise error dicts
- `agents/storage/tools.py` — reference for `propose_*` HITL pattern
- `agents/tests/sre/test_sre_tools.py` — reference for test structure (success/error/sdk-missing)

### Established Patterns
- Tool function: `start_time = time.monotonic()` at entry; `duration_ms` in both try/except
- Module-level SDK scaffold: `try: from azure.mgmt.xxx import XxxClient except ImportError: XxxClient = None`
- System prompt: `## {Domain} Agent` heading with tool list, fallback behavior, safety constraints
- Orchestrator routing: `domain` field in incident payload maps to agent via `DOMAIN_AGENT_MAP`

### Integration Points
- `services/api-gateway/main.py` — add `database` routing entry
- `agents/orchestrator/agent.py` — add Database agent to handoff registry
- `terraform/modules/container_apps/` — new Container App resource for `ca-database-prod`

</code_context>

<specifics>
## Specific Ideas

- Cosmos DB 429 throttle triage is the primary success scenario: surface RU utilisation %, hot partition key, propose throughput increase via HITL
- `query_postgres_slow_queries` goes via Log Analytics (not direct pg connection) — same pattern as `query_logs` in monitor tools
- `propose_*` functions return a structured approval request dict (never execute directly) — follow `propose_remediation` in SRE agent

</specifics>

<deferred>
## Deferred Ideas

- Redis Cache tools — deferred to a future phase
- MySQL tools — deferred (less common in the platform estate)
- Direct database connection diagnostics (pg_stat_activity etc.) — security risk, deferred

</deferred>
