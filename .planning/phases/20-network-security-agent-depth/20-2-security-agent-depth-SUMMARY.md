# Plan 20-2 Execution Summary — Security Agent Depth

**Plan:** 20-2
**Title:** Security Agent Depth
**Phase:** 20 — Network & Security Agent Depth
**Wave:** 2 (parallel with 20-3)
**Status:** COMPLETE
**Executed:** 2026-04-02

---

## Objective

Give the Security Agent real investigative depth by implementing its 3 existing stub tools and adding 4 new tools covering the full Defender for Cloud security posture surface: secure score, RBAC assignments, policy compliance, and public endpoint scanning.

---

## Tasks Executed

### Task 1 — Populate `agents/security/requirements.txt` ✅
**Commit:** `feat(security): populate requirements.txt with 4 azure-mgmt packages`

Replaced the empty file with 4 required packages:
- `azure-mgmt-security>=4.0.0` — Defender alerts + secure score
- `azure-mgmt-authorization>=4.0.0` — RBAC assignments
- `azure-mgmt-policyinsights>=1.1.0` — Policy compliance
- `azure-mgmt-network>=27.0.0` — Public IP scanning

### Task 2 — Add module-level scaffolding ✅
**Commit:** `feat(security): add module scaffold — lazy imports, logger, sdk availability`

Added to `agents/security/tools.py`:
- `import logging`, `import time`, `from datetime import datetime, timedelta, timezone`
- `from shared.auth import get_credential` (was missing)
- Lazy import guards for all 5 packages: SecurityCenter, AuthorizationManagementClient, PolicyInsightsClient, NetworkManagementClient, MonitorManagementClient, LogsQueryClient/LogsQueryStatus
- `logger = logging.getLogger(__name__)`
- `_log_sdk_availability()` logging all 5 packages at module load
- `_extract_subscription_id()` helper (same as compute agent pattern)

### Task 3 — Implement `query_defender_alerts` and `query_iam_changes` ✅
Both tools fully implemented with real SDK calls:
- `query_defender_alerts`: `SecurityCenter.alerts.list()` with severity post-filtering, full alert dict mapping, `duration_ms` timing
- `query_iam_changes`: `MonitorManagementClient.activity_logs.list()` with IAM-focused filter, separates results into rbac_changes / keyvault_policy_changes / identity_operations

### Task 4 — Implement `query_keyvault_diagnostics` (revised signature) ✅
Updated stub with Log Analytics approach:
- New signature: `(vault_name, workspace_id=None, timespan_hours=2)`
- `workspace_id` empty/None → returns `query_status: "skipped"` gracefully
- Uses `LogsQueryClient.query_workspace()` with `AzureDiagnostics` KQL
- Maps rows to `operations` list; populates `anomaly_indicators` for Unauthorized/Forbidden results

### Task 5 — Add `query_secure_score` and `query_rbac_assignments` ✅
- `query_secure_score`: uses `SecurityCenter.secure_scores.get(subscription_id, "ascScore")` — hard-coded `"ascScore"` identifier documented in docstring
- `query_rbac_assignments`: `list_for_scope(scope)` or `list_for_subscription()` with `max_results=100` cap and `truncated: bool` flag

### Task 6 — Add `query_policy_compliance` and `scan_public_endpoints` ✅
- `query_policy_compliance`: `PolicyInsightsClient.policy_states.list_query_results_for_subscription("latest", ...)` with `complianceState eq 'NonCompliant'` filter; optional `policy_definition_id` filter
- `scan_public_endpoints`: `NetworkManagementClient.public_ip_addresses.list_all()` with resource_group extraction from resource ID path

### Task 7 — Create test suite ✅
**Commit:** `test(security): add 28 unit tests for all security agent tools`

Created:
- `agents/tests/security/__init__.py` (empty)
- `agents/tests/security/test_security_tools.py` — 28 tests across 8 classes

**All 28 tests pass.**

---

## Test Results

```
agents/tests/security/ — 28 passed, 0 failed, 1 warning (urllib3 SSL)

TestAllowedMcpTools          3 tests — PASS
TestQueryDefenderAlerts      4 tests — PASS
TestQueryIamChanges          3 tests — PASS
TestQueryKeyvaultDiagnostics 4 tests — PASS
TestQuerySecureScore         4 tests — PASS
TestQueryRbacAssignments     4 tests — PASS
TestQueryPolicyCompliance    3 tests — PASS
TestScanPublicEndpoints      3 tests — PASS
```

---

## Success Criteria Verification

- [x] `agents/security/requirements.txt` has exactly 4 packages with correct version pins
- [x] `agents/security/tools.py` has no stub bodies remaining — all 7 tools make real SDK calls (or return `skipped` for workspace_id guard)
- [x] `query_keyvault_diagnostics` has `workspace_id: Optional[str] = None` in its signature
- [x] `query_keyvault_diagnostics` returns `query_status: "skipped"` when workspace_id is empty/None
- [x] `query_rbac_assignments` has `max_results: int = 100` and returns `truncated: bool`
- [x] `query_secure_score` passes the literal `"ascScore"` string to `secure_scores.get()`
- [x] All 7 tools have `time.monotonic()` and `duration_ms` in both try and except
- [x] `_log_sdk_availability()` logs all 5 packages at module load
- [x] `agents/tests/security/__init__.py` exists
- [x] `agents/tests/security/test_security_tools.py` has 28 test functions (≥26 required)
- [x] `pytest agents/tests/security/` passes with zero failures
- [x] No wildcard imports; all lazy import guards follow `try/except ImportError` pattern

---

## Commits

| Commit | Message |
|--------|---------|
| `1d04994` | feat(security): populate requirements.txt with 4 azure-mgmt packages |
| `0fe064d` | feat(security): add module scaffold — lazy imports, logger, sdk availability |
| `c31325f` | test(security): add 28 unit tests for all security agent tools |

---

## Key Decisions

- **All 7 tools in one commit:** Tasks 2-6 were implemented as a single coherent rewrite of `tools.py` since the scaffold (Task 2) is a prerequisite for compiling all implementations — separating would have left partially-implemented files.
- **`_make_logs_query_response` helper:** Uses a `MagicMock()` sentinel instead of importing `LogsQueryStatus` directly — `azure.monitor.query` is not installed in the test environment. Tests that need the equality check patch `LogsQueryStatus` and set `response.status = mock_status_cls.SUCCESS` to ensure comparison works correctly.
- **`query_iam_changes` uses `identity_operations` bucket for unmatched events:** Events that don't match RBAC or KV prefixes are placed in `identity_operations` (could include service principal operations) — consistent with the existing stub's return structure.
