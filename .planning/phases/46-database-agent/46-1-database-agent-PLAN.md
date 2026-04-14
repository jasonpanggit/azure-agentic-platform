---
id: 46-1
wave: 1
phase: 46
title: Database Agent
depends_on: []
files_modified:
  - agents/database/__init__.py
  - agents/database/agent.py
  - agents/database/tools.py
  - agents/database/requirements.txt
  - agents/database/Dockerfile
  - agents/tests/database/__init__.py
  - agents/tests/database/test_database_tools.py
  - agents/orchestrator/agent.py
autonomous: true
---

## Objective

Build a Database domain agent covering Azure Cosmos DB, PostgreSQL Flexible Server, and
Azure SQL Database. Deploys as `ca-database-prod` Container App and is routed when the
orchestrator receives `domain: database` incidents or operator queries about database
performance and health.

## must_haves

- 12 tool functions across 3 database engines decorated with `@ai_function`
- Lazy SDK imports (`try/except ImportError`) for all azure-mgmt-* packages
- `start_time = time.monotonic()` at every tool entry; `duration_ms` in both try/except
- Tools never raise — always return structured error dicts on failure
- `propose_*` tools return HITL dicts with `approval_required: True`
- `DATABASE_AGENT_SYSTEM_PROMPT` with tool list and safety constraints
- `create_database_agent()` factory returning a `ChatAgent`
- 50+ unit tests covering success, SDK exception, and SDK-missing paths
- Orchestrator `DOMAIN_AGENT_MAP` updated with `"database": "database_agent"`
- Orchestrator system prompt updated with `database → database_agent` routing rule
- Orchestrator `RESOURCE_TYPE_TO_DOMAIN` updated for Cosmos DB, PostgreSQL, Azure SQL

## Tasks

<task id="46-1-T1">
Create `agents/database/__init__.py` (empty package marker).
</task>

<task id="46-1-T2">
Create `agents/database/tools.py` with 12 tools:

**Cosmos DB tools:**
1. `get_cosmos_account_health(account_name, resource_group, subscription_id)` — ARM health,
   service availability, provisioning state, backup policy
2. `get_cosmos_throughput_metrics(account_id, database_name, container_name, timespan)` —
   Monitor metrics: TotalRequestUnits, NormalizedRUConsumption, ServerSideLatency,
   Http429s, ThrottledRequests; surface RU utilisation % and 429 rate
3. `query_cosmos_diagnostic_logs(workspace_id, account_name, timespan_hours)` — KQL via
   azure-monitor-query LogsQueryClient; surface hot partition keys, high-latency ops, 429s
4. `propose_cosmos_throughput_scale(account_id, container_id, current_ru, proposed_ru,
   rationale)` — HITL proposal dict with approval_required=True

**PostgreSQL Flexible Server tools:**
5. `get_postgres_server_health(server_name, resource_group, subscription_id)` — ARM server
   properties, HA state, replication role, maintenance window, storage percent
6. `get_postgres_metrics(server_id, timespan, interval)` — Monitor metrics:
   cpu_percent, memory_percent, storage_percent, connections_failed,
   connections_succeeded, io_consumption_percent
7. `query_postgres_slow_queries(workspace_id, server_name, timespan_hours, threshold_ms)` —
   KQL via LogsQueryClient on AzureDiagnostics table; returns slow query events
8. `propose_postgres_sku_scale(server_id, current_sku, proposed_sku, rationale)` —
   HITL proposal dict with approval_required=True

**Azure SQL tools:**
9. `get_sql_database_health(server_name, database_name, resource_group, subscription_id)` —
   ARM database properties, service tier, status, zone redundancy, elastic pool info
10. `get_sql_dtu_metrics(database_id, timespan, interval)` — Monitor metrics:
    dtu_consumption_percent, cpu_percent, storage_percent, deadlock, failed_connections,
    sessions_percent; surfaces DTU/vCore utilisation
11. `query_sql_query_store(workspace_id, server_name, database_name, timespan_hours)` —
    KQL on AzureDiagnostics / AzureMetrics; top slow queries by avg duration
12. `propose_sql_elastic_pool_move(database_id, target_elastic_pool_id, rationale)` —
    HITL proposal dict with approval_required=True
</task>

<task id="46-1-T3">
Create `agents/database/agent.py` with:
- `DATABASE_AGENT_SYSTEM_PROMPT` (## Database Agent heading, tool list, triage workflow,
  Cosmos 429 throttle triage, safety constraints)
- `create_database_agent()` factory returning `ChatAgent`
- `create_database_agent_version(project)` for Foundry versioned registration
- Entry point `if __name__ == "__main__"` following sre/agent.py pattern
</task>

<task id="46-1-T4">
Create `agents/database/requirements.txt` pinning:
- azure-mgmt-cosmosdb (Cosmos DB management)
- azure-mgmt-rdbms (PostgreSQL Flexible Server management)
- azure-mgmt-sql (Azure SQL management)
- azure-mgmt-monitor (metrics queries)
- azure-monitor-query (Log Analytics KQL)
</task>

<task id="46-1-T5">
Create `agents/database/Dockerfile` following `agents/storage/Dockerfile` pattern:
- `ARG BASE_IMAGE` + `FROM ${BASE_IMAGE}`
- `COPY requirements.txt .` + `RUN pip install ...`
- `COPY . ./database/`
- `CMD ["python", "-m", "database.agent"]`
</task>

<task id="46-1-T6">
Create `agents/tests/database/__init__.py` (empty package marker).
</task>

<task id="46-1-T7">
Create `agents/tests/database/test_database_tools.py` with 50+ unit tests:
- `TestAllowedMcpTools` — count, contents, no wildcards
- `TestGetCosmosAccountHealth` — success, error, SDK missing
- `TestGetCosmosThroughputMetrics` — success, error, SDK missing
- `TestQueryCosmosDiagnosticLogs` — success, error, SDK missing
- `TestProposeCosmosThroughputScale` — returns approval_required=True, all fields present
- `TestGetPostgresServerHealth` — success, error, SDK missing
- `TestGetPostgresMetrics` — success, error, SDK missing
- `TestQueryPostgresSlowQueries` — success, error, SDK missing
- `TestProposePostgresSkuScale` — returns approval_required=True, all fields present
- `TestGetSqlDatabaseHealth` — success, error, SDK missing
- `TestGetSqlDtuMetrics` — success, error, SDK missing
- `TestQuerySqlQueryStore` — success, error, SDK missing
- `TestProposeSqlElasticPoolMove` — returns approval_required=True, all fields present
</task>

<task id="46-1-T8">
Update `agents/orchestrator/agent.py`:
- Add `"database": "database_agent"` to `DOMAIN_AGENT_MAP`
- Add `"database → database_agent"` routing rule to `ORCHESTRATOR_SYSTEM_PROMPT`
- Add `"database"` to conversational routing rules (mentions "cosmos", "cosmosdb",
  "postgresql", "postgres", "azure sql", "sql database" → `database_agent`)
- Add database resource type prefixes to `RESOURCE_TYPE_TO_DOMAIN`:
  `"microsoft.documentdb"`, `"microsoft.dbforpostgresql"`, `"microsoft.sql"` → `"database"`
- Add `"database"` to `_A2A_DOMAINS` list
</task>
