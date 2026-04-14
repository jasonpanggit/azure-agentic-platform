# Phase 65 Code Review — Azure MCP Server v2 Upgrade and New Capabilities

**Reviewer:** Claude (automated)
**Date:** 2026-04-14
**Branch:** `gsd/phase-45-azure-mcp-server-v2-upgrade-and-new-capabilities`
**Depth:** Standard
**Files reviewed:** 25

---

## Summary

| Area | Result |
|---|---|
| v2 MCP tool name migration | ✅ PASS |
| `query_container_app_health` implementation | ✅ PASS (with minor gaps) |
| Test completeness and correctness | ✅ PASS (one missing path) |
| Security | ⚠️ 2 MEDIUM issues |

**Overall:** Phase is shippable. Two medium issues should be addressed before or shortly after merge. No blockers.

---

## Focus Area 1 — v2 MCP Tool Name Migration

### Verdict: PASS

All 8 agents have fully migrated from v1 dotted tool names to v2 namespace-level intent tools. No dotted names (e.g., `monitor.query_logs`, `compute.list_vms`) remain in any `ALLOWED_MCP_TOOLS` list.

### Agent-by-agent allowlist audit

| Agent | `ALLOWED_MCP_TOOLS` entries | Dotted names | v1 residue |
|---|---|---|---|
| `arc` | `arc_servers_list`, `arc_k8s_list`, `arc_extensions_list`, `arc_policy_list`, `arc_connectivity_check`, `arc_guest_config_list`, `arc_data_services_list`, `arc_servers_update`, `arc_k8s_apply`, `monitor`, `resourcehealth` (11) | None | None |
| `compute` | `compute`, `monitor`, `resourcehealth`, `advisor`, `appservice` (5) | None | None |
| `eol` | `monitor`, `resourcehealth` (2) | None | None |
| `network` | `monitor`, `resourcehealth`, `advisor`, `compute` (4) | None | None |
| `patch` | `monitor`, `resourcehealth` (2) | None | None |
| `security` | `keyvault`, `role`, `monitor`, `resourcehealth`, `advisor` (5) | None | None |
| `sre` | `monitor`, `applicationinsights`, `advisor`, `resourcehealth`, `containerapps` (5) | None | None |
| `storage` | `storage`, `fileshares`, `monitor`, `resourcehealth` (4) | None | None |

**Arc note:** The Arc agent retains underscore-named tools (e.g., `arc_servers_list`). These are Custom Arc MCP Server tools, not Azure MCP Server v2 tools, and the naming convention is correct and intentional.

### Infrastructure references

- **`services/azure-mcp-server/Dockerfile`**: `ARG AZURE_MCP_VERSION=2.0.0` — pinned correctly.
- **`CLAUDE.md`**: References `microsoft/mcp` (new repo location, moved from `Azure/azure-mcp`) — correct.
- **`agents/tests/test_mcp_v2_migration.py`**: Cross-cutting `test_no_dotted_mcp_tool_names` parametrized across all 8 agents provides regression protection. `test_dockerfile_mcp_version` guards pin version. Both tests are well-structured.

---

## Focus Area 2 — `query_container_app_health` Implementation

**Location:** `agents/sre/tools.py`, lines 1034–1143

### Verdict: PASS (with LOW observability gap)

The implementation follows the platform's tool function pattern correctly for the happy path and error path.

### What's correct

- **Lazy import guard**: `ContainerAppsAPIClient` imported at module level inside `try/except ImportError`; check `if ContainerAppsAPIClient is None` returns structured error immediately. ✅
- **Never-raise pattern**: All exceptions caught; both outer `except Exception` and inner revision `except Exception` return/log without re-raising. ✅
- **Structured error dicts**: All error paths return `{"query_status": "error", "error": ..., "duration_ms": ...}`. ✅
- **`start_time = time.monotonic()`**: Present at entry inside the context manager. ✅
- **`duration_ms` on all paths**: Both success `try` and outer `except` blocks compute and include `duration_ms`. ✅
- **Inner revision isolation**: Revision listing wrapped in its own `try/except`; failure logs warning and continues with empty `active_revisions` rather than aborting the tool call. ✅
- **`subscription_id` guard**: Checks env var before entering the OTel context manager; returns error dict if missing. ✅
- **`instrument_tool_call` context manager**: Used correctly around the main execution block. ✅

### Finding LOW-001 — Observability gap: early guards emit no OTel spans

**Severity:** LOW
**File:** `agents/sre/tools.py`
**Lines:** ~1040–1060 (SDK-missing guard and sub_id guard)

The `if ContainerAppsAPIClient is None` and `if not subscription_id` early-return paths execute *before* entering the `instrument_tool_call` context manager. These failure cases do not produce OpenTelemetry spans.

For SDK-missing errors this is acceptable (infrastructure misconfiguration, not a runtime tool failure). For missing-subscription-id errors this is a minor gap — a debugging session for an unexpected missing-env-var failure would find no span trace.

**Recommendation:** Move the `start_time = time.monotonic()` call and SDK-missing / sub_id guards *inside* the `with instrument_tool_call(...)` block, or wrap the early returns in a span. Low priority.

---

## Focus Area 3 — Test Completeness and Correctness

### Verdict: PASS (one missing path)

### What's well-covered

- **`TestAllowedMcpTools` in each agent's test file**: Verifies entry count, no wildcards, no dotted names, expected entries present. The compute and network tests are exemplary templates.
- **`test_no_dotted_names_across_all_agents`** in `agents/tests/integration/test_mcp_tools.py`: Parametrized cross-agent regression test. Strong protection against v1 name re-introduction.
- **`TestQueryContainerAppHealth`** in `agents/tests/sre/test_sre_tools.py`: 4 tests covering happy path, API exception, SDK-missing, and missing subscription_id. All assertions are correct.
- **EOL tool tests**: Comprehensive coverage of `normalize_product_slug`, `classify_eol_status`, `query_endoflife_date`, `query_ms_lifecycle`, `scan_estate_eol`, cache helpers, and `_fetch_with_retry`.
- **Patch agent tests**: Verify MCPTool mounting when `AZURE_MCP_SERVER_URL` is set; confirm `discover_arc_workspace` is registered.
- **OTel span tests**: `record_tool_call_span` tests use `"compute.list_vms"` as tool_name — this is testing the span-recording function's parameter handling, not MCP compliance. Acceptable and not a v1 residue concern.

### Finding TEST-001 — Missing test: revision-listing exception path in `query_container_app_health`

**Severity:** LOW
**File:** `agents/tests/sre/test_sre_tools.py`

`query_container_app_health` contains an inner `try/except` block around revision listing. The intent is: if revision listing fails, the tool should still return success with `active_revisions: []` (or partial data) and log a warning.

This path has no test. A regression that breaks inner error isolation (e.g., by removing the inner try/except) would not be caught.

**Recommended test:**
```python
def test_revision_list_error_still_returns_app_data(self):
    """Inner revision-listing exception should not abort the tool call."""
    with patch("agents.sre.tools.ContainerAppsAPIClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.container_apps.get.return_value = MagicMock(
            name="test-app",
            provisioning_state="Succeeded",
            latest_revision_name="rev-1",
        )
        mock_client.container_apps_revisions.list.side_effect = Exception("revision API error")

        result = query_container_app_health(
            container_app_name="test-app",
            resource_group="test-rg",
            subscription_id="00000000-0000-0000-0000-000000000000",
        )

    assert result["query_status"] == "success"
    assert result["active_revisions"] == []
    assert "duration_ms" in result
```

---

## Focus Area 4 — Security

### Verdict: ⚠️ 2 MEDIUM issues, no CRITICAL

### PASS items

- **No hardcoded secrets**: All credentials via `DefaultAzureCredential` or environment variables. ✅
- **Dockerfile non-root user**: `mcp` user created and used; container does not run as root. ✅
- **Internal-only ingress**: `--dangerously-disable-http-incoming-auth` flag removed from Dockerfile. Defense-in-depth via Container Apps internal ingress only. ✅
- **Input validation**: Tool functions validate required parameters before making SDK calls. ✅

---

### Finding SEC-001 — OData filter injection in `query_ms_lifecycle`

**Severity:** MEDIUM
**File:** `agents/eol/tools.py`
**Approximate location:** `query_ms_lifecycle` function, OData filter construction

The Microsoft Lifecycle API OData filter is constructed with an unsanitized `product` parameter:

```python
f"contains(productName,'{product}')"
```

If `product` contains a single quote (e.g., `"Microsoft's Server"` → `contains(productName,'Microsoft's Server')`), the OData query becomes syntactically malformed and the request will fail.

**Context and risk assessment:**
- The `product` value originates from the LLM (via `@ai_function` call), not from direct user input to the API.
- The OData `contains()` filter does not support SQL-style injection into query *logic* in the same way — a malformed value causes query failure, not data leakage.
- On failure, the tool catches the exception and returns an error dict; `endoflife.date` serves as fallback.
- **Risk:** Query failure causing unnecessary fallback to `endoflife.date` for products with apostrophes in their names (e.g., `"Microsoft's SQL Server"`). No data exfiltration risk.

**Recommended fix:**
```python
# Escape single quotes by doubling them (OData convention)
safe_product = product.replace("'", "''")
odata_filter = f"contains(productName,'{safe_product}')"
```

---

### Finding SEC-002 — PostgreSQL password not URL-encoded in DSN

**Severity:** MEDIUM
**File:** `agents/eol/tools.py`
**Function:** `resolve_postgres_dsn`

The DSN URL is constructed by substituting raw environment variable values. If `POSTGRES_PASSWORD` contains URL-reserved characters (`@`, `/`, `#`, `?`, `:`), the `asyncpg` DSN parser will misinterpret the password as part of the host, port, or path segments.

```python
# Current (vulnerable to special chars in password)
dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
```

**Risk:** Connection failure when password contains special characters. No security vulnerability per se, but a correctness/reliability issue. Passwords with `@` are particularly likely to cause silent DSN misparse.

**Recommended fix:**
```python
from urllib.parse import quote_plus

dsn = f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}"
```

---

## Additional Findings (Out of Scope for Focus Areas)

### Finding BUG-001 — `finding_id` slug scope check always False in `scan_estate_eol`

**Severity:** LOW
**File:** `agents/eol/tools.py`
**Function:** `scan_estate_eol` (or `_get_eol_status` inner closure)

```python
finding_id = f"eol-{slug if 'slug' in dir() else <fallback>}"
```

`dir()` returns module-level and class-level names, not local variable names. `slug` is a local variable; `'slug' in dir()` is always `False`. The intent was to use `'slug' in locals()` or a conditional based on whether the `normalize_product_slug()` call succeeded.

**Impact:** The `finding_id` always uses the fallback path. Functionally harmless (findings still get IDs), but the slug-based ID path is dead code. Pre-existing bug, not introduced in this phase.

**Recommended fix:**
```python
# Option 1: use locals()
finding_id = f"eol-{slug if 'slug' in locals() else <fallback>}"

# Option 2: initialize slug = None before the call, then check
slug = None
slug, _ = normalize_product_slug(product_name)
finding_id = f"eol-{slug}" if slug else f"eol-{<fallback>}"
```

---

### Finding ARCH-001 — `patch/agent.py` imports MCPTool from wrong package

**Severity:** MEDIUM
**File:** `agents/patch/agent.py`, line 25

```python
# patch/agent.py (current — inconsistent)
from azure.ai.projects.models import MCPTool

# All other agents that mount MCP servers (e.g., eol/agent.py)
from agent_framework import MCPTool
```

Every other agent in the codebase that mounts an MCP server imports `MCPTool` from `agent_framework`. The patch agent imports it from `azure.ai.projects.models`.

These are different classes. `agent_framework.MCPTool` is the Microsoft Agent Framework's MCP integration class, designed to work with `ChatAgent`. `azure.ai.projects.models.MCPTool` is the Foundry SDK's model class for MCP tool descriptors.

At runtime, the patch agent's MCP tool mounting may silently fail or behave incorrectly because `ChatAgent` expects the `agent_framework.MCPTool` type for its tools list.

**Recommended fix:**
```python
# agents/patch/agent.py
from agent_framework import MCPTool  # match all other agents
```

Verify by running the patch agent's existing MCPTool mounting test after the fix.

---

## Findings Summary Table

| ID | Severity | File | Description |
|---|---|---|---|
| SEC-001 | **MEDIUM** | `agents/eol/tools.py` | OData filter constructed with unescaped `product` — single quotes cause query failure |
| SEC-002 | **MEDIUM** | `agents/eol/tools.py` | PostgreSQL password not URL-encoded in DSN — special chars break connection |
| ARCH-001 | **MEDIUM** | `agents/patch/agent.py` | `MCPTool` imported from `azure.ai.projects.models` instead of `agent_framework` |
| TEST-001 | LOW | `agents/tests/sre/test_sre_tools.py` | Missing test for inner revision-listing exception path in `query_container_app_health` |
| LOW-001 | LOW | `agents/sre/tools.py` | Early-exit guards in `query_container_app_health` emit no OTel spans |
| BUG-001 | LOW | `agents/eol/tools.py` | `'slug' in dir()` always False — dead code, pre-existing, harmless |

---

## Recommended Actions

### Before merge (or immediately after)
1. **ARCH-001** — Fix `patch/agent.py` MCPTool import. One-line change; low regression risk.
2. **SEC-001** — Escape single quotes in OData filter with `product.replace("'", "''")`.
3. **SEC-002** — URL-encode PostgreSQL password with `urllib.parse.quote_plus`.

### Post-merge (backlog)
4. **TEST-001** — Add revision-listing exception test to `TestQueryContainerAppHealth`.
5. **LOW-001** — Move early guards inside `instrument_tool_call` context in `query_container_app_health`.
6. **BUG-001** — Fix `slug` scope check to use `locals()` in `scan_estate_eol`.
