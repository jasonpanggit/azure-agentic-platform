# Agent Tests

Unit and integration test suites for all domain agents and shared utilities. Tests are organized by agent domain under `agents/tests/` and run with `pytest` from the repository root.

## Responsibilities
- Verify `@ai_function` tool contracts: inputs, outputs, and error handling for every agent
- Mock Azure SDK calls to keep tests hermetic (no live Azure dependencies)
- Validate `IncidentMessage` envelope construction and domain routing logic
- Run integration smoke tests for inter-agent handoffs, HITL approval flows, and MCP v2 tool migration
- Cover shared utilities: auth, envelope, routing, approval manager, runbook retrieval, SOP lifecycle

## Key Files
- `compute/` — unit tests for compute agent tools (Activity Log, Log Analytics, Resource Health, Monitor metrics, ARG)
- `network/` — unit tests for network agent tools (VNet, NSG, connectivity check)
- `storage/` — unit tests for storage agent tools (metrics, Activity Log, Resource Health)
- `security/` — unit tests for security agent tools (Defender, Key Vault, RBAC, policy)
- `arc/` — unit tests for Arc agent tools (HybridCompute, K8s, guest config)
- `sre/` — unit tests for SRE agent tools (availability, change analysis, Advisor)
- `patch/` — unit tests for patch agent tools (ARG assessment, KB-to-CVE, runbook search)
- `eol/` — unit tests for EOL agent tools (endoflife.date client, PostgreSQL cache, ARG inventory)
- `appservice/` — unit tests for App Service agent tools
- `containerapps/` — unit tests for Container Apps agent tools
- `database/` — unit tests for Database agent tools (Cosmos DB, PostgreSQL, SQL)
- `finops/` — unit tests for FinOps agent tools (cost breakdown, idle VM, budget forecast)
- `messaging/` — unit tests for Messaging agent tools (Service Bus, Event Hubs)
- `shared/` — unit tests for shared utilities (auth, envelope, routing, approval, runbook, SOP, budget)
- `integration/` — integration and smoke tests: handoff flows, HITL approval, MCP tool migration, phase smoke tests
- `test_mcp_v2_migration.py` — validates that all agents use v2 namespace-level MCP tool names (no dotted v1 names)
