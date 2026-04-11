# Summary — Plan 20-02: Security Agent Real SDK Tool Implementations

## Result: COMPLETE

All 4 tasks executed successfully. The Security agent now has 7 fully implemented tools making real Azure SDK calls, replacing all 3 stubs and adding 4 new capabilities.

## Tasks Completed

| Task | Title | Commit | Status |
|------|-------|--------|--------|
| 20-02-01 | Update requirements.txt with 6 SDK packages | `524e65f` | Done |
| 20-02-02 | Replace 3 stub tools with real SDK implementations | `8e5e90a` | Done |
| 20-02-03 | Add 4 new tools (secure score, RBAC, policy, public endpoints) | `8e5e90a` | Done (combined with 02) |
| 20-02-04 | Update agent.py — register tools, expand system prompt | `a5726a1` | Done |

> Tasks 20-02-02 and 20-02-03 were combined into a single commit because both modify `agents/security/tools.py` as a full file rewrite — splitting would have required an artificial intermediate state.

## Changes Made

### `agents/security/requirements.txt`
- Added 6 Azure SDK packages: `azure-mgmt-security>=5.0.0`, `azure-mgmt-authorization>=4.0.0`, `azure-mgmt-policyinsights>=1.0.0`, `azure-mgmt-monitor>=6.0.0`, `azure-monitor-query>=1.3.0`, `azure-mgmt-network>=27.0.0`

### `agents/security/tools.py` (166 → 650+ lines)
- **Module scaffold:** 6 lazy SDK imports in try/except blocks, `_log_sdk_availability()` checking all 6 packages, `_extract_subscription_id()` helper
- **Tool 1 — `query_defender_alerts`:** SecurityCenter SDK, severity filter, `asc_location` parameter, 200-alert cap
- **Tool 2 — `query_keyvault_diagnostics`:** LogsQueryClient KQL query on AzureDiagnostics table, `workspace_id` parameter with env var fallback, anomaly detection (caller diversity, failed ops, bulk ops)
- **Tool 3 — `query_iam_changes`:** MonitorManagementClient Activity Log filtered by Microsoft.Authorization, categorizes into rbac_changes/keyvault_policy_changes/identity_operations
- **Tool 4 — `query_secure_score`:** SecurityCenter `secure_scores.get(secure_score_name="ascScore")` — current score, max, percentage, weight
- **Tool 5 — `query_rbac_assignments`:** AuthorizationManagementClient with scope/principal_id filters, 500-assignment cap
- **Tool 6 — `query_policy_compliance`:** PolicyInsightsClient filtered by compliance state, 100-result default cap
- **Tool 7 — `scan_public_endpoints`:** NetworkManagementClient `public_ip_addresses.list_all()` with associated/unassociated counts
- **ALLOWED_MCP_TOOLS:** 7 entries (added `advisor.list_recommendations`)
- All 7 tools follow established pattern: `instrument_tool_call`, `start_time = time.monotonic()`, `duration_ms` in both try/except, never raise

### `agents/security/agent.py`
- Updated imports to include all 7 tools
- Expanded system prompt triage workflow from 9 to 13 steps (new steps 8-11: secure score, RBAC audit, policy compliance, public endpoint scan)
- Updated `ChatAgent(tools=[...])` to register all 7 tools
- Preserved TRIAGE-003, REMEDI-001 constraints and credential exposure immediate escalation rule

## Verification

| Check | Expected | Actual |
|-------|----------|--------|
| `@ai_function` count in tools.py | 7 | 7 |
| SDK packages in requirements.txt | 6 | 6 |
| ALLOWED_MCP_TOOLS entries | 7 | 7 |
| Tools registered in ChatAgent | 7 | 7 |
| `start_time = time.monotonic()` calls | 7 | 7 |
| `"query_status": "error"` in except blocks | 7 | 7 |
| System prompt contains `TRIAGE-003` | Yes | Yes |
| System prompt contains `REMEDI-001` | Yes | Yes |
| System prompt contains credential escalation rule | Yes | Yes |

## Must-Haves Checklist

- [x] All 3 existing stub tools replaced with real SDK calls (SecurityCenter, LogsQueryClient, MonitorManagementClient)
- [x] 4 new tools added: `query_secure_score`, `query_rbac_assignments`, `query_policy_compliance`, `scan_public_endpoints`
- [x] `requirements.txt` updated with 6 new SDK packages
- [x] All 7 tools follow the established pattern (instrument_tool_call, start_time, duration_ms, never raise)
- [x] `ALLOWED_MCP_TOOLS` includes `advisor.list_recommendations` (7 entries)
- [x] System prompt updated with all 7 tools in triage workflow
- [x] Credential exposure immediate escalation rule preserved in system prompt
- [x] `ChatAgent(tools=[...])` registers all 7 tools
