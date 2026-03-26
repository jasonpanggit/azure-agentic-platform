---
plan: "03-02"
status: complete
completed_date: 2026-03-26
branch: feat/03-02-arc-agent-upgrade
commit: 7cd2ff0
---

# Plan 03-02 Summary: Arc Agent Upgrade

## Objective

Replace the Phase 2 Arc Agent stub with a fully operational ChatAgent that mounts the
Arc MCP Server via McpTool, implements the TRIAGE-006 triage workflow, and exposes
@ai_function tools matching the compute agent pattern.

## Files Modified

| File | Change |
|------|--------|
| `agents/arc/tools.py` | **Created** — @ai_function wrappers + ALLOWED_MCP_TOOLS |
| `agents/arc/agent.py` | **Replaced** — Phase 2 stub → full Phase 3 ChatAgent |
| `agents/arc/requirements.txt` | **Updated** — Phase 3 Arc SDK packages |

## Tasks Completed

### Task 02.01 — Create Arc Agent tools.py ✅

Created `agents/arc/tools.py` with:
- `ALLOWED_MCP_TOOLS`: explicit list of 12 tools (9 Arc MCP Server + 3 Azure MCP Server)
  — no wildcards, replaces Phase 2 empty list (AGENT-005)
- `@ai_function query_activity_log`: mandatory first RCA step (TRIAGE-003)
- `@ai_function query_log_analytics`: mandatory before diagnosis (TRIAGE-002)
- `@ai_function query_resource_health`: mandatory before diagnosis (TRIAGE-002)
- Every `@ai_function` uses `instrument_tool_call` from `agents/shared/otel.py` (AUDIT-001)

ALLOWED_MCP_TOOLS list:
```
arc_servers_list, arc_servers_get, arc_extensions_list, arc_k8s_list,
arc_k8s_get, arc_k8s_gitops_status, arc_data_sql_mi_list, arc_data_sql_mi_get,
arc_data_postgresql_list, monitor.query_logs, monitor.query_metrics,
resourcehealth.get_availability_status
```

### Task 02.02 — Replace Arc Agent stub with full ChatAgent ✅

Completely replaced `agents/arc/agent.py`. All Phase 2 stub code removed:
- `pending_phase3` status: **removed**
- `ALLOWED_MCP_TOOLS: list[str] = []`: **replaced** with import from tools.py
- `handle_arc_incident` function: **removed**

New agent includes:
- `ARC_AGENT_SYSTEM_PROMPT`: 7-step TRIAGE-006 workflow encoded in system prompt
- `create_arc_agent()`: factory that validates `ARC_MCP_SERVER_URL`, creates `McpTool`,
  returns `ChatAgent` with `tool_resources=[arc_mcp_tool]`
- `McpTool(server_label="arc-mcp", server_url=os.environ["ARC_MCP_SERVER_URL"], allowed_tools=ALLOWED_MCP_TOOLS)`

TRIAGE-006 system prompt workflow (steps 1–7):
1. Activity Log check (TRIAGE-003) — mandatory before any Arc MCP calls
2. Arc connectivity check via `arc_servers_list` / `arc_k8s_list` (MONITOR-004)
3. Extension health via `arc_extensions_list` for non-Connected servers (MONITOR-005)
4. GitOps reconciliation via `arc_k8s_gitops_status` for K8s clusters (MONITOR-006)
5. Log Analytics + Resource Health (TRIAGE-002)
6. Structured `TriageDiagnosis` with `confidence_score` (TRIAGE-004)
7. Remediation proposal with explicit human approval gate (REMEDI-001)

### Task 02.03 — Update Arc Agent requirements.txt ✅

Replaced Phase 2 placeholder with Phase 3 Arc SDK packages:
```
azure-mgmt-hybridcompute==9.0.0       # HybridComputeManagementClient
azure-mgmt-hybridkubernetes==1.1.0    # ConnectedKubernetesClient (NOT connectedk8s)
azure-mgmt-azurearcdata==1.0.0        # AzureArcDataManagementClient (NOT arcdata)
azure-mgmt-kubernetesconfiguration==3.1.0  # Flux GitOps status (MONITOR-006)
httpx>=0.27.0                         # Arc MCP Server integration tests
```

## Acceptance Criteria Results

All plan acceptance criteria passed:

| Check | Result |
|-------|--------|
| `agents/arc/tools.py` exists | ✅ |
| `ALLOWED_MCP_TOOLS` non-empty, ≥9 tools | ✅ 12 tools |
| All Arc MCP tools listed explicitly | ✅ |
| No wildcards | ✅ |
| `@ai_function` wrappers present | ✅ 3 functions |
| `instrument_tool_call` used in every @ai_function | ✅ |
| Phase 2 `pending_phase3` removed | ✅ 0 occurrences |
| `handle_arc_incident` removed | ✅ 0 occurrences |
| `ARC_AGENT_SYSTEM_PROMPT` with TRIAGE-006 steps | ✅ |
| `McpTool` mounting with `ARC_MCP_SERVER_URL` | ✅ |
| `tool_resources=[arc_mcp_tool]` in `ChatAgent` | ✅ |
| `create_arc_agent()` factory | ✅ |
| Phase 3 SDK packages in requirements.txt | ✅ |

## Requirements Satisfied

| Requirement | Status |
|-------------|--------|
| TRIAGE-006: Arc triage workflow (Activity Log → connectivity → extensions → GitOps → diagnosis) | ✅ |
| TRIAGE-002: Log Analytics + Resource Health mandatory before diagnosis | ✅ |
| TRIAGE-003: Activity Log as first RCA step (2h window) | ✅ |
| TRIAGE-004: confidence_score in every diagnosis | ✅ |
| REMEDI-001: No remediation without human approval | ✅ |
| AGENT-005: ALLOWED_MCP_TOOLS non-empty explicit list | ✅ |
| MONITOR-004: Arc connectivity check in triage | ✅ |
| MONITOR-005: Extension health check in triage | ✅ |
| MONITOR-006: GitOps reconciliation check in triage | ✅ |
| AUDIT-001: OTel tracing on all tool calls | ✅ |

## Notes

- The `arc_servers_connectivity_check` tool referenced in the plan's `must_haves` section
  uses `arc_servers_list` as the actual tool name (matching the ALLOWED_MCP_TOOLS list
  in the plan's task body and the RESEARCH.md Section 6.3). The system prompt references
  both `arc_servers_list` and describes it as the connectivity check step, which is
  consistent with the Arc MCP Server tool naming.
- The `arc_data_sql_mi_get` tool was added to ALLOWED_MCP_TOOLS beyond the minimal list
  in RESEARCH.md Section 6.3, matching the fuller list in the plan's Task 02.01 body.
  Total: 12 tools (exceeds the ≥9 requirement).
- `ARC_MCP_SERVER_URL` raises `ValueError` at startup with no fallback — as required by
  must_have #3.
