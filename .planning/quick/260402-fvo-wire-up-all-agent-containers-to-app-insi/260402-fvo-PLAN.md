# Quick Task: Wire Up All Agent Containers to App Insights

**ID:** 260402-fvo
**Type:** observability
**Branch:** `quick/260402-fvo-app-insights-wiring`

---

## Current State

### What's already working:
- **Terraform**: `APPLICATIONINSIGHTS_CONNECTION_STRING` env var is injected into ALL containers (agent-apps module line 78-80, arc-mcp-server module line 64-67, teams-bot line 339-341) via a secret reference. The plumbing is complete at the infra layer.
- **All 9 Python agents** (orchestrator, compute, network, storage, security, arc, sre, patch, eol): Already import and call `setup_telemetry()` from `agents/shared/otel.py`, which calls `configure_azure_monitor()`. Fully wired.
- **API Gateway** (`services/api-gateway`): Calls `configure_azure_monitor()` in `main.py` (line 198). Has manual span helpers in `instrumentation.py`. Fully wired.
- **Teams Bot** (`services/teams-bot`): Has `src/instrumentation.ts` that calls `useAzureMonitor()`. Imported as first line in `index.ts`. Fully wired.

### What's NOT wired (gap):
- **Arc MCP Server** (`services/arc-mcp-server`): Has `azure-monitor-opentelemetry` + `opentelemetry-sdk` in `requirements.txt` (lines 23-24) and receives `APPLICATIONINSIGHTS_CONNECTION_STRING` from Terraform, but **never calls `configure_azure_monitor()`**. No instrumentation code exists in `server.py` or `__main__.py`. The dependency is installed but the SDK is never initialized.

---

## Tasks

### Task 1: Add OTel initialization to Arc MCP Server
**Files:** `services/arc-mcp-server/__main__.py`

Add `configure_azure_monitor()` call before the FastMCP app starts (same pattern as api-gateway). Must be called before uvicorn starts so auto-instrumentation hooks into HTTP requests.

**Implementation:**
1. In `__main__.py`, import `os` and `configure_azure_monitor` from `azure.monitor.opentelemetry`
2. Call `configure_azure_monitor(connection_string=...)` at module level (before `_serve()`) reading from `APPLICATIONINSIGHTS_CONNECTION_STRING`
3. Guard with `if connection_string:` to allow local dev without App Insights
4. Add a `logging.info/warning` for OTel status (consistent with teams-bot pattern)

**Acceptance:**
- [ ] `configure_azure_monitor()` called when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set
- [ ] Graceful no-op when env var is missing (local dev)
- [ ] Log line indicating OTel status (configured or disabled)
- [ ] No import errors — `azure-monitor-opentelemetry` already in requirements.txt

### Task 2: Add unit test for Arc MCP Server OTel initialization
**Files:** `services/arc-mcp-server/tests/test_otel_init.py` (new)

Verify the OTel initialization logic:
1. Test that `configure_azure_monitor` is called when `APPLICATIONINSIGHTS_CONNECTION_STRING` is present
2. Test that it is NOT called when the env var is missing
3. Use `unittest.mock.patch` to mock `configure_azure_monitor`

**Acceptance:**
- [ ] 2 tests: configured + disabled paths
- [ ] Tests pass with `pytest services/arc-mcp-server/tests/test_otel_init.py`
- [ ] No real Azure connections needed

### Task 3: Verify all containers — create observability audit checklist
**Files:** `docs/observability-wiring.md` (new)

Create a quick reference doc showing the OTel wiring status of every container:

| Container | OTel SDK | Init Call | Env Var (Terraform) | Status |
|-----------|----------|-----------|---------------------|--------|
| orchestrator | `agents/shared/otel.py` | `setup_telemetry()` | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Wired |
| compute | ... | ... | ... | Wired |
| ... | ... | ... | ... | ... |
| arc-mcp-server | `azure-monitor-opentelemetry` | `configure_azure_monitor()` | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Wired (after Task 1) |

**Acceptance:**
- [ ] All 12 containers documented (9 agents + api-gateway + teams-bot + arc-mcp-server)
- [ ] Each row shows: SDK package, init function, Terraform env var source, status
- [ ] Detection-plane (Fabric UDF) excluded — no container, runs serverless in Fabric

---

## Out of Scope
- Adding custom/manual spans to arc-mcp-server (future task — auto-instrumentation is sufficient for now)
- Detection-plane observability (Fabric serverless, no container)
- Web-UI OTel (Next.js client-side, different pattern — structured logging already added in 260401-o1l)
