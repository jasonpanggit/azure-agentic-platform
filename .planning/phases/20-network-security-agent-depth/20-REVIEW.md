# Phase 20 — Network / Security / SRE Agent Depth Review

**Reviewed:** 2026-04-10  
**Scope:** `agents/network/`, `agents/security/`, `agents/sre/` — tools, agents, tests, integration  
**Depth:** Standard  

---

## Executive Summary

All three agents are production-quality implementations. The tool layer is consistent and disciplined, tests are well-structured and cover success / error / SDK-missing paths for every tool, and the integration test suite correctly exercises the `TriageDiagnosis` / `RemediationProposal` contracts across all three domains. Four issues warrant attention before shipping: one correctness gap in the KV diagnostics query, one type annotation inconsistency in `TriageDiagnosis`, one missing network requirements pin, and one test gap in `check_connectivity`. None are blockers, but the KV issue in particular is worth fixing before production use.

---

## 1. Network Agent

### 1.1 `agents/network/tools.py`

**Strengths**
- All 7 tools follow the platform's module-level SDK scaffold pattern exactly (`try/except ImportError`, `_log_sdk_availability`, `_extract_subscription_id`).
- Every tool records `start_time = time.monotonic()` at entry and computes `duration_ms` in both `try` and `except` blocks.
- Structured error return dicts are shape-consistent with success returns — callers never need to branch on missing keys.
- `check_connectivity` correctly handles the LRO (Long-Running Operation) timeout separately from SDK-level errors, returning a distinct `"timeout"` status — a subtle but important distinction for the Orchestrator.
- The `ConnectivityParameters` / `ConnectivitySource` / `ConnectivityDestination` models have their own `try/except ImportError` block and a second `None` check inside the tool body — thorough handling for a rarely-installed model trio.
- `query_flow_logs` correctly extracts the nested `flow_analytics_configuration.network_watcher_flow_analytics_configuration` path and gracefully handles `None` at each level.

**Issues**

| Severity | Location | Description |
|---|---|---|
| LOW | `query_vnet_topology` L276 | `subnet.delegations` is iterated but only `d.service_name` is captured. If a delegation entry has a `None` service_name the list will contain `None` values, which the agent cannot reason about. A `d.service_name or ""` guard would be safer. |
| INFO | `ALLOWED_MCP_TOOLS` | The list has 5 MCP tools but no mention of `resourcehealth.list_events`, which the SRE system prompt uses. No functional impact on the network agent itself, but the cross-agent reference is worth noting for completeness. |

### 1.2 `agents/network/agent.py`

- System prompt enumerates all 10 tool names in the `{allowed_tools}` block by string-formatting `ALLOWED_MCP_TOOLS + [...]`. This is solid and self-documenting.
- The 10-step mandatory triage workflow in the prompt is well-structured and tightly coupled to TRIAGE-002/003/004 and REMEDI-001. Each step names the specific tool or MCP call to invoke.
- RBAC scope comment (`Network Contributor`) matches Terraform intent.
- The `if __name__ == "__main__"` entry point imports `from_agent_framework` correctly and calls `.run()`.

**Issues**

| Severity | Location | Description |
|---|---|---|
| INFO | System prompt Step 6 | `check_connectivity` requires the Network Watcher extension on the source VM. The prompt says "Note: The source VM must have the Network Watcher extension installed" in the docstring, but the system prompt itself does not warn the LLM. If the extension is absent the tool returns `query_status: error` and the agent will have no guidance to suggest enabling it first. A one-line note in the prompt would improve agent reasoning. |

### 1.3 `agents/network/requirements.txt`

```
azure-mgmt-network>=27.0.0
```

**Issues**

| Severity | Location | Description |
|---|---|---|
| MEDIUM | `requirements.txt` | Version is lower-bounded only. The `azure-mgmt-network` SDK has had breaking API changes across major versions. Given this is a pre-release RC project, pinning to a compatible range (e.g., `>=27.0.0,<28.0.0`) would prevent a silent regression if `28.x` ships with a breaking rename. The same pattern issue applies to security and SRE requirements (see §2.3). |

---

## 2. Security Agent

### 2.1 `agents/security/tools.py`

**Strengths**
- Seven distinct tools covering the full security posture surface: Defender alerts, KV diagnostics, IAM changes, Secure Score, RBAC assignments, policy compliance, and public endpoint scanning.
- The `query_iam_changes` Activity Log filter scopes to `Microsoft.Authorization` only, which is the correct minimal-privilege approach for TRIAGE-003 (IAM-first).
- `query_keyvault_diagnostics` uses `LogsQueryClient` (azure-monitor-query) for KQL rather than the Management SDK — correct because KV diagnostic logs land in Log Analytics, not the control plane.
- `scan_public_endpoints` correctly derives `resource_group` from the resource ID parts rather than requiring a caller-supplied param — sensible UX decision.
- The 200-alert cap in `query_defender_alerts` and the 500-assignment cap in `query_rbac_assignments` prevent LLM context overflow.
- The `anomaly_indicators` logic in `query_keyvault_diagnostics` (caller diversity, failed ops, bulk operations) is a meaningful first-pass heuristic that adds real signal beyond raw data.

**Issues**

| Severity | Location | Description |
|---|---|---|
| MEDIUM | `query_keyvault_diagnostics` L306–309 | The KQL string inlines `vault_name` directly via f-string: `` f" | where Resource =~ '{vault_name}'" ``. If `vault_name` contains a single quote (rare but possible) this produces a malformed KQL query. While KV vault names are restricted to alphanumeric + hyphens (so this is a LOW/theoretical risk in practice), it is an injection-style bug and the fix is simple: use the `parameters` argument of `query_workspace` or at minimum validate the name matches `^[a-zA-Z0-9-]{3,24}$` at entry. |
| LOW | `query_iam_changes` L493–495 | The `elif` for `keyvault_policy_changes` checks `"microsoft.keyvault/vaults/accesspolicies"` (all lower-cased after `op_lower = op_name.lower()`). The real ARM operation name is `Microsoft.KeyVault/vaults/accessPolicies` — the mixed-case form lower-cased is `microsoft.keyvault/vaults/accesspolicies`. This is correct. However, the `elif` does NOT catch `Microsoft.KeyVault/vaults/write` operations, which happen when Key Vault settings (soft-delete, purge protection) are changed. This is a minor coverage gap — the operation silently falls through to no category. Not a bug but worth noting. |
| LOW | `query_keyvault_diagnostics` L357 | `from collections import Counter` is an inline import inside a function body. It should be moved to the top of the file per PEP 8 / isort conventions. Functionally harmless. |
| INFO | `query_secure_score` L587–596 | The tool uses `hasattr(score, "current_score")` instead of `getattr(score, "current_score", 0.0)`. `hasattr` is redundant here — all attributes will exist on the SDK model object (they'd just be `None`). Minor style inconsistency compared with other tools that consistently use `getattr(..., None)`. |

### 2.2 `agents/security/agent.py`

- System prompt's immediate escalation rule (Step 3) is correctly placed *before* Resource Health and before hypothesis generation — this matches the security constraint requirement.
- The `data plane` prohibition for Key Vault is explicit in both the docstring of `query_keyvault_diagnostics` and in the Safety Constraints section of the system prompt — belt-and-suspenders.
- Tool registration in `create_security_agent()` matches the 7 tools exported from `security.tools` exactly.

**Issues**

None significant.

### 2.3 `agents/security/requirements.txt`

**Issues**

| Severity | Location | Description |
|---|---|---|
| MEDIUM | All version specifiers | Same upper-bound omission as network. `azure-mgmt-security>=5.0.0`, `azure-mgmt-authorization>=4.0.0`, `azure-mgmt-policyinsights>=1.0.0`, `azure-mgmt-monitor>=6.0.0`, `azure-monitor-query>=1.3.0`, `azure-mgmt-network>=27.0.0` — all lower-bounded only. Recommend adding compatible upper bounds. |
| INFO | `azure-monitor-query>=1.3.0` | The `LogsQueryStatus` enum is accessed as `response.status == LogsQueryStatus.SUCCESS`. In `azure-monitor-query` 1.3.x the value is `LogsQueryStatus.SUCCESS`. If the library ships a 2.x with an API rename, this would silently return empty operations with no error. The `hasattr` guard before the status check partially mitigates this. |

---

## 3. SRE Agent

### 3.1 `agents/sre/tools.py`

**Strengths**
- `correlate_cross_domain` is the standout piece: a composite tool that aggregates four sub-calls with independent per-call error isolation. Each sub-error is captured but does not poison the overall result. Partial failure is reported in the `correlation_summary` string rather than silently dropped. This is exactly the right pattern for a cross-domain tool.
- `propose_remediation` is intentionally a no-op structurally (just constructs and returns the proposal dict) — this correctly enforces REMEDI-001 at the type level. The `requires_approval: True` flag is hardcoded and cannot be overridden by the caller.
- `_percentile` is extracted as a pure helper with its own type annotation and docstring. The index-based approach avoids the `statistics` module (not always available in constrained envs) and the behaviour is deterministic and testable.
- `query_availability_metrics` correctly computes `availability_percent` as the mean of *average* data points, not minimum — appropriate for SLA calculations.
- `query_performance_baselines` requests `Average,Maximum,Minimum` aggregations in a single API call rather than three calls — efficient.

**Issues**

| Severity | Location | Description |
|---|---|---|
| LOW | `correlate_cross_domain` L919 | The availability sub-call uses `f"PT{timespan_hours}H"` to construct a timespan string. This produces `"PT2H"` for the default 2-hour window, which is valid ISO 8601. However if `timespan_hours > 24` it continues to emit `"PT48H"` rather than `"P2D"`. Both are valid ISO 8601 but the Azure Monitor API accepts both — this is a style note, not a functional bug. |
| LOW | `query_service_health` L505 | `str(evt_type) if evt_type is not None else None` works, but if `evt_type` is an SDK enum, `str()` will produce `"EventType.ServiceIssue"` in some SDK versions rather than just `"ServiceIssue"`. The test mocks use `MagicMock(event_type="ServiceIssue")` (a plain string), so the test would pass while production may differ. A `.value` access (like other enum-backed fields in the codebase) or a `getattr(evt_type, 'value', str(evt_type))` pattern would be safer. This same pattern appears in `query_advisor_recommendations` for `category` and `impact`. |
| INFO | `query_change_analysis` L779 | `str(getattr(change, "change_type", None))` will produce `"None"` (the string) if `change_type` is absent. The string `"None"` in the `change_type` field is misleading. `getattr(change, "change_type", None)` without the `str()` wrapper is cleaner and leaves `None` as `None`. Same pattern in `query_service_health` L511 for `status` and L523 for `level`. |

### 3.2 `agents/sre/agent.py`

- System prompt correctly positions `query_service_health` as the MONITOR-003 fulfillment in Step 3, alongside `resourcehealth.get_availability_status`.
- Arc Fallback section in the system prompt is explicit and tells the agent to state "Full Arc diagnostics require Phase 3 Arc MCP Server" — correct and honest behaviour for the interim phase.
- Tool list in `create_sre_agent()` matches the 7 tools exported from `sre.tools` exactly.

**Issues**

None significant.

### 3.3 `agents/sre/requirements.txt`

**Issues**

| Severity | Location | Description |
|---|---|---|
| MEDIUM | All specifiers | `azure-mgmt-resourcehealth==1.0.0b6` is the only pinned exact version. The `azure-mgmt-changeanalysis>=1.0.0` and `azure-mgmt-advisor>=9.0.0` specifiers are lower-bounded only. At minimum, the pinned pre-release SDK (`1.0.0b6`) should be flagged with a comment explaining it is pinned because the stable release lacks `events.list_by_subscription_id`. This is invisible to a future developer who might bump it. |

---

## 4. Tests

### 4.1 `tests/network/test_network_tools.py`

- Full 3-path coverage (success, SDK error, SDK missing) for all 7 tools. ✓
- `check_connectivity` correctly has 4 paths: success-reachable, success-unreachable, timeout (poller raises), and generic SDK error. ✓
- `_extract_subscription_id` has parametrized invalid-input tests including edge cases (empty string, no-subscriptions path). ✓
- `_mock_with_name` helper correctly works around the `MagicMock(name=...)` quirk by setting `.name` post-construction. ✓

**Issues**

| Severity | Location | Description |
|---|---|---|
| LOW | `TestCheckConnectivity.test_returns_error_when_sdk_missing` L823 | The test patches `ConnectivityParameters` to `None` but leaves `NetworkManagementClient` as a live mock. In the production code, the SDK-missing check for `NetworkManagementClient` happens first (L869-871), which would also fire. To specifically test the `ConnectivityParameters is None` branch, the test should also patch `NetworkManagementClient` to a non-None mock. Currently the test is correct *only* because patching `ConnectivityParameters = None` triggers `raise ImportError("...connectivity models are not installed")` at L871 — but this depends on execution order assumptions. Adding `@patch("agents.network.tools.NetworkManagementClient")` as an additional decorator would make the test intent unambiguous. |
| INFO | All test classes | The `mock_instrument` context manager boilerplate (`__enter__`, `__exit__`) is repeated verbatim across all ~70 test methods. A shared `pytest.fixture` for the instrument mock would reduce noise while preserving clarity. |

### 4.2 `tests/security/test_security_tools.py`

- Full 3–4-path coverage for all 7 tools. ✓
- `TestQueryRbacAssignments` has an additional `test_principal_id_filter` test validating client-side filter logic — good. ✓
- `TestQueryPolicyCompliance.test_max_results_cap` creates 150 states and verifies the cap at 100 — a correct boundary test. ✓

**Issues**

| Severity | Location | Description |
|---|---|---|
| INFO | `TestQueryKeyvaultDiagnostics.test_returns_success_with_operations` | The test mocks `LogsQueryStatus.SUCCESS` as a class-level patch but sets `mock_response.status = mock_status_cls.SUCCESS`. This is subtly fragile: `mock_status_cls` is an auto-created `MagicMock` whose `.SUCCESS` attribute is also a `MagicMock`. The assertion `response.status == LogsQueryStatus.SUCCESS` in production compares a `MagicMock` to another `MagicMock` reference — they are the same object so the equality holds, but only because of Python identity, not value comparison. The test is correct, but it would be cleaner to use `mock_status_cls.SUCCESS = "Success"` to make the intent explicit. |
| INFO | `TestQueryDefenderAlerts` | No test for the 200-alert cap. The cap is a correctness boundary worth a test. Low priority. |

### 4.3 `tests/sre/test_sre_tools.py`

- `TestCorrelateCrossDomain` has three cases: all succeed, one fails, all fail — correctly exercises the fault-isolation promise. ✓
- `TestPercentile` tests the `_percentile` helper in isolation including edge cases (empty list, single element). ✓
- `TestQueryPerformanceBaselines.test_returns_success_with_baselines` correctly verifies p95 at index 8 of a 10-element list and checks `avg`. ✓

**Issues**

| Severity | Location | Description |
|---|---|---|
| INFO | `TestQueryServiceHealth.test_event_type_filter` | The mock events use plain strings for `event_type` (e.g., `"ServiceIssue"`). The production code does `str(getattr(event, "event_type", None))`. In production the SDK returns an enum; `str(enum)` in some SDK versions produces `"EventType.ServiceIssue"`, which would not match the filter string `"ServiceIssue"`. The test passes but could be masking the issue noted in §3.1. |

### 4.4 `tests/integration/test_triage.py`

**Strengths**
- Validates `TriageDiagnosis` and `RemediationProposal` construction including validation (confidence out-of-range, invalid risk level). ✓
- `to_envelope` tests verify the `validate_envelope` path, providing an end-to-end contract test for the diagnosis → envelope → validation chain. ✓
- Domain-specific flow tests (`TestNetworkTriageFlow`, `TestSecurityTriageFlow`, `TestSreTriageFlow`) simulate realistic incidents with evidence, cross-domain escalation, and approval-required remediation. ✓
- `test_security_cross_domain_escalation_to_network` validates both the diagnosis fields AND the envelope payload — two-layer assertion. ✓

**Issues**

| Severity | Location | Description |
|---|---|---|
| MEDIUM | `shared/triage.py` L55 | The `TriageDiagnosis.__init__` signature declares `evidence: List[str]`, but the integration tests pass `List[Dict]` (e.g., `evidence=[{"source": "logs", "excerpt": "..."}]`). This is a type annotation lie — the runtime works because Python does not enforce generic typing, but mypy/pyright would flag every integration test call. The annotation should be `List[Any]` or `List[Dict[str, Any]]` to match actual usage. |
| LOW | `tests/integration/test_triage.py` | All tests are marked `@pytest.mark.integration` but `test_triage.py` constructs only in-memory objects (no I/O, no Azure calls). These are actually unit tests for shared data structures. The `integration` marker may cause them to be skipped in fast unit-test CI runs. Consider marking them `@pytest.mark.unit` or removing the marker entirely. |

---

## 5. Cross-Cutting Observations

### 5.1 Code Duplication

`_extract_subscription_id` is defined identically in `network/tools.py`, `security/tools.py`, and `sre/tools.py`. This function is also almost certainly defined in other agent modules. It should be extracted to `shared/utils.py` (or wherever the platform's shared utilities live) and imported. The duplication is low-risk but adds maintenance surface.

`_mock_with_name` is duplicated across `test_network_tools.py`, `test_security_tools.py`, and `test_sre_tools.py`. A shared test fixture or conftest utility would clean this up.

### 5.2 OTel `correlation_id` / `thread_id` Empty Strings

Every `instrument_tool_call` invocation across all three agents passes `correlation_id=""` and `thread_id=""`. These are presumably populated at agent invocation time from the request context. The current wiring passes empty strings at the tool level, which means OTel traces will lack correlation context. This appears to be a platform-level limitation (no context propagation from agent thread into `@ai_function` scope) rather than a bug in these files, but it limits tracing fidelity. Worth tracking as a known gap.

### 5.3 Requirements Pinning (Summary)

| Agent | Status |
|---|---|
| Network | Lower-bound only — needs upper bounds |
| Security | Lower-bound only — needs upper bounds |
| SRE | `azure-mgmt-resourcehealth==1.0.0b6` pinned (correct, undocumented), rest lower-bound only |

### 5.4 System Prompt Consistency

All three system prompts correctly:
- Name the specific tools for each mandatory step
- Reference TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001 codes
- State RBAC scope
- Enumerate allowed tools via `{allowed_tools}` format block

One inconsistency: the Network agent system prompt says "10-step workflow" but lists 10 items labelled 1–10 consistently. The Security agent has 13 steps (1–13). The SRE agent has 9 steps. No functional problem, but if the Orchestrator ever parses step counts from the prompt these differences could matter.

---

## 6. Issue Severity Summary

| Severity | Count | Key Items |
|---|---|---|
| MEDIUM | 3 | KV diagnostics KQL injection risk, requirements upper-bound omission (×2 agents), `TriageDiagnosis.evidence` type annotation mismatch |
| LOW | 7 | `service_health` enum str coercion, `"None"` string from `str(None)`, subnet delegation None values, connectivity SDK-missing test order, test markers on integration tests, `Counter` inline import |
| INFO | 8 | `hasattr` style inconsistency, OTel empty correlation_id, `_extract_subscription_id` duplication, `_mock_with_name` duplication, Network Watcher extension hint in prompt, `LogsQueryStatus` comparison pattern, alert cap missing test, enum str() fragility in tests |

---

## 7. Recommendations (Prioritised)

1. **[MEDIUM] Fix KV diagnostics KQL injection** — add a vault name validation guard (`^[a-zA-Z0-9-]{3,24}$`) or switch to the `parameters` dict in `query_workspace`. One-line fix.

2. **[MEDIUM] Fix `TriageDiagnosis.evidence` type annotation** — change `List[str]` → `List[Any]` or `List[Dict[str, Any]]` in `shared/triage.py` L55. One-character change per import; fixes mypy alignment with every domain's actual usage.

3. **[MEDIUM] Add upper bounds to requirements** — add compatible upper bounds to all three `requirements.txt` files to prevent silent breakage when SDK major versions increment.

4. **[LOW] Fix `str(enum)` pattern in SRE tools** — use `.value` access or `getattr(x, 'value', str(x))` for `event_type`, `category`, `impact` in `query_service_health` and `query_advisor_recommendations`.

5. **[LOW] Move `Counter` import to top of `security/tools.py`** — trivial PEP 8 fix.

6. **[LOW] Clarify `check_connectivity` SDK-missing test** — add `NetworkManagementClient` mock to make the test intent unambiguous.

7. **[INFO] Extract `_extract_subscription_id` to `shared/utils.py`** — dedup across 3+ agent modules.

8. **[INFO] Add `azure-mgmt-resourcehealth==1.0.0b6` comment in `sre/requirements.txt`** — explain why it's pinned to a pre-release version.
