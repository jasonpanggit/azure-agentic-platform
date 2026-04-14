---
id: 46-1
phase: 46
status: complete
date: 2026-04-14
commits: []
---

## Summary

Built the Database domain agent covering Azure Cosmos DB, PostgreSQL Flexible Server, and
Azure SQL Database. The agent deploys as `ca-database-prod` and is routed by the orchestrator
for `domain: database` incidents and operator queries mentioning cosmos, postgresql, azure sql,
throughput, DTU, or elastic pool keywords.

## Tasks Completed

- **T1** `agents/database/__init__.py` — package marker created
- **T2** `agents/database/tools.py` — 12 tool functions across 3 database engines:
  - Cosmos DB: `get_cosmos_account_health`, `get_cosmos_throughput_metrics`,
    `query_cosmos_diagnostic_logs`, `propose_cosmos_throughput_scale`
  - PostgreSQL: `get_postgres_server_health`, `get_postgres_metrics`,
    `query_postgres_slow_queries`, `propose_postgres_sku_scale`
  - Azure SQL: `get_sql_database_health`, `get_sql_dtu_metrics`,
    `query_sql_query_store`, `propose_sql_elastic_pool_move`
  - All tools follow the lazy-import, never-raise, `start_time`/`duration_ms` pattern
  - All `propose_*` tools return `approval_required: True` HITL dicts (REMEDI-001)
- **T3** `agents/database/agent.py` — `DATABASE_AGENT_SYSTEM_PROMPT` with triage workflow
  per engine, safety constraints, `create_database_agent()` factory, and
  `create_database_agent_version()` for Foundry versioned registration
- **T4** `agents/database/requirements.txt` — pinned azure-mgmt-cosmosdb, azure-mgmt-rdbms,
  azure-mgmt-sql, azure-mgmt-monitor, azure-monitor-query
- **T5** `agents/database/Dockerfile` — non-root user, linux/amd64, follows storage agent pattern
- **T6** `agents/tests/database/__init__.py` — test package marker
- **T7** `agents/tests/database/test_database_tools.py` — 44 unit tests covering success, SDK
  exception, and SDK-missing paths for all 12 tools plus ALLOWED_MCP_TOOLS and
  `_extract_subscription_id` helper (44 collected, 44 passed)
- **T8** `agents/orchestrator/agent.py` — updated:
  - `DOMAIN_AGENT_MAP` += `"database": "database_agent"`
  - System prompt routing rules += database keywords (cosmos, postgresql, azure sql, etc.)
  - System prompt tool allowlist += `database_agent`
  - `RESOURCE_TYPE_TO_DOMAIN` += `microsoft.documentdb`, `microsoft.dbforpostgresql`,
    `microsoft.sql` → `"database"`
  - `_A2A_DOMAINS` += `"database"`

## Test Results

```
44 passed, 1 warning in 0.41s
```

All tests pass. The 4 initial failures (MagicMock `name` parameter collision with column name
attribute, and SKU mock attribute) were fixed by explicitly assigning `.name` on mock objects
rather than passing `name=` to the MagicMock constructor.
