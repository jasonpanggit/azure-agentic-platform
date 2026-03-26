# Plan 03-01 Summary: Arc MCP Server — Core + Terraform

**Status:** Complete
**Date:** 2026-03-26
**Branch:** feat/03-02-arc-agent-upgrade
**Commit:** 561c902

---

## What Was Built

### Service: `services/arc-mcp-server/`

11 files created implementing a standalone FastMCP server for Azure Arc resources.

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring — AGENT-005 reference |
| `__main__.py` | Entry point: `mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)` |
| `auth.py` | `DefaultAzureCredential` via `@lru_cache(maxsize=1)` — matches `agents/shared/auth.py` |
| `models.py` | 10 Pydantic models — all `Optional[str]` for nullable fields, `bool = False` for flags |
| `server.py` | FastMCP instance + 9 `@mcp.tool()` registrations |
| `tools/arc_servers.py` | `arc_servers_list_impl`, `arc_servers_get_impl`, `arc_extensions_list_impl` |
| `tools/arc_k8s.py` | `arc_k8s_list_impl`, `arc_k8s_get_impl`, `arc_k8s_gitops_status_impl` |
| `tools/arc_data.py` | `arc_data_sql_mi_list_impl`, `arc_data_postgresql_list_impl`, `arc_data_sql_mi_get_impl` |
| `requirements.txt` | Pinned packages: `mcp[cli]==1.26.0`, hybridcompute 9.0.0, hybridkubernetes 1.1.0, azurearcdata 1.0.0, kubernetesconfiguration 3.1.0 |
| `Dockerfile` | Standalone `python:3.11-slim` — does NOT extend `agents/Dockerfile.base` |

### Terraform Module: `terraform/modules/arc-mcp-server/`

3 files. Internal-only Container App with Reader RBAC across Arc subscriptions.

| File | Key Decisions |
|------|--------------|
| `main.tf` | `ingress { external_enabled = false, target_port = 8080 }` — explicit internal ingress block (unlike agent-apps which omits ingress entirely for internal apps) |
| `variables.tf` | `arc_subscription_ids`, `arc_disconnect_alert_hours`, standard infra vars |
| `outputs.tf` | `arc_mcp_server_url` = `http://{fqdn}/mcp` for use as `ARC_MCP_SERVER_URL` |

### Dev Environment: `terraform/envs/dev/main.tf`

`module "arc_mcp_server"` block appended after `module "rbac"` with all required inputs wired from upstream modules.

---

## Requirements Satisfied

| Requirement | How Satisfied |
|-------------|--------------|
| **AGENT-005** | FastMCP server with 9 tools covering Arc Servers, K8s, and Data Services |
| **AGENT-006** | All 4 list tools return `total_count = len(items)` after exhausting `ItemPaged` |
| **MONITOR-004** | `_is_prolonged_disconnect()` reads `ARC_DISCONNECT_ALERT_HOURS` env var (default 1h), sets `prolonged_disconnection=True` for `Disconnected` servers over threshold |
| **MONITOR-005** | `arc_extensions_list` + `arc_servers_get` return `ArcExtensionHealth` with `provisioning_state` and `instance_view.status` for AMA, DependencyAgent, Change Tracking, GuestConfiguration |
| **MONITOR-006** | `arc_k8s_gitops_status` uses `SourceControlConfigurationClient.flux_configurations.list()` — ARM-native, no `kubectl` or K8s SDK |

---

## Must-Have Checklist

- [x] `FastMCP("arc-mcp-server", stateless_http=True)` — stateless for multi-replica
- [x] `mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)` in `__main__.py`
- [x] All list tools return `total_count = len(items)` (AGENT-006)
- [x] `arc_servers_list` detects `prolonged_disconnection` via `ARC_DISCONNECT_ALERT_HOURS` (MONITOR-004)
- [x] `arc_extensions_list` returns health via `provisioning_state` + `instance_view.status` (MONITOR-005)
- [x] `arc_k8s_gitops_status` uses `SourceControlConfigurationClient` — no kubectl (MONITOR-006)
- [x] All Pydantic models use `Optional[str]` for nullable fields — no `ValidationError` on real data
- [x] Terraform `ingress.external_enabled = false` with explicit ingress block (not absent ingress)
- [x] `@lru_cache(maxsize=1)` on `get_credential()` — no per-request instantiation

---

## Verification Results

All 27 acceptance criteria checks passed:
- 11/11 service files exist and contain correct content
- 3/3 Terraform module files exist and contain correct patterns
- 9/9 `@mcp.tool()` registrations confirmed
- All `total_count` assertions verified in each list tool
- `ARC_DISCONNECT_ALERT_HOURS` env var consumption verified
- No `kubernetes` client in `requirements.txt` (ARM-only Flux detection)
- `external_enabled = false` confirmed in Terraform
- `terraform fmt -check` passes

---

## Key Design Decisions

### Ingress Pattern Deviation from agent-apps
The `agent-apps` module uses a `dynamic "ingress"` block that **omits** the block entirely for `ingress_external = false`. This gives agents no internal FQDN. The Arc MCP Server requires an internal FQDN so agents can call it via HTTP. The solution is an explicit `ingress { external_enabled = false }` block — this gives an internal FQDN without public exposure.

### Credential Caching
`HybridComputeManagementClient` and other SDK clients are subscription-scoped and created per tool call. Only `DefaultAzureCredential` is cached via `@lru_cache(maxsize=1)` (matching `agents/shared/auth.py`). This is the correct pattern — no per-request credential instantiation.

### arc_k8s SDK Property Handling
The `_serialize_cluster()` function checks both `cluster.properties.{field}` and `cluster.{field}` to handle potential SDK version variations in `azure-mgmt-hybridkubernetes==1.1.0`. This prevents `AttributeError` on real cluster objects.

### Arc Data Services Note
`azure-mgmt-azurearcdata==1.0.0` is old with sparse coverage. The `_get_arcdata_client()` uses a deferred import to avoid import errors at startup if the SDK has issues. A note is preserved in `arc_data.py` about fallback to direct ARM REST calls if needed.

---

## Files Modified

```
services/arc-mcp-server/__init__.py          (new)
services/arc-mcp-server/__main__.py          (new)
services/arc-mcp-server/server.py            (new)
services/arc-mcp-server/auth.py              (new)
services/arc-mcp-server/models.py            (new)
services/arc-mcp-server/tools/__init__.py    (new)
services/arc-mcp-server/tools/arc_servers.py (new)
services/arc-mcp-server/tools/arc_k8s.py    (new)
services/arc-mcp-server/tools/arc_data.py   (new)
services/arc-mcp-server/Dockerfile          (new)
services/arc-mcp-server/requirements.txt    (new)
terraform/modules/arc-mcp-server/main.tf    (new)
terraform/modules/arc-mcp-server/variables.tf (new)
terraform/modules/arc-mcp-server/outputs.tf (new)
terraform/envs/dev/main.tf                  (modified — arc_mcp_server module appended)
```

---

## Next Steps

- **03-02** (already in progress on this branch): Arc Agent upgrade — replace the Phase 2 stub with full triage workflow, mount Arc MCP Server via `McpTool`, populate `ALLOWED_MCP_TOOLS`
- **03-03**: Unit tests — pagination exhaustion (AGENT-006), `prolonged_disconnection` logic (MONITOR-004), Pydantic model validation
- **03-04**: E2E-006 — Playwright test with mock ARM server seeded with 120 Arc servers
