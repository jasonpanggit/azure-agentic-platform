---
phase: 20-network-security-agent-depth
plan: "04"
subsystem: agents/tests
tags: [unit-tests, integration-tests, network-agent, security-agent, sre-agent, triage, pytest, mock, coverage]

# Dependency graph
requires:
  - phase: 20-01
    provides: Network agent 7 real SDK tools
  - phase: 20-02
    provides: Security agent 7 real SDK tools
  - phase: 20-03
    provides: SRE agent 7 real SDK tools
provides:
  - 93 unit tests for Network (31), Security (30), SRE (32) agent tools
  - 6 integration triage flow tests for network, security, SRE domains
  - Full regression verification (407 passed, 0 regressions)
affects: [test-suite, ci-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: [_mock_with_name helper for MagicMock .name attribute trap, 3-path testing (success/error/sdk-missing), composite tool sub-call patching]

key-files:
  created:
    - agents/tests/network/__init__.py
    - agents/tests/network/test_network_tools.py
    - agents/tests/security/__init__.py
    - agents/tests/security/test_security_tools.py
    - agents/tests/sre/__init__.py
    - agents/tests/sre/test_sre_tools.py
  modified:
    - agents/tests/integration/test_triage.py

key-decisions:
  - "_mock_with_name helper created to work around MagicMock(name=x) setting internal repr instead of .name attribute"
  - "Each tool tested with 3 paths: success (valid SDK response), error (SDK exception), SDK-missing (client=None)"
  - "correlate_cross_domain tested by patching 4 internal sub-calls directly instead of SDK clients"
  - "Integration triage tests validate end-to-end TriageDiagnosis + RemediationProposal + envelope for each domain"

patterns-established:
  - "MagicMock name attribute trap: construct mock first, then assign m.name = value as post-construction step"
  - "3-path tool testing pattern: success/error/sdk-missing for every @ai_function tool"
  - "Composite tool testing: patch sub-tool calls, not underlying SDK clients, for unit isolation"
  - "Domain triage flow tests: diagnosis + cross-domain escalation + remediation + envelope validation"

requirements-completed: [PROD-003, TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001]

# Metrics
duration: 25min
completed: 2026-04-10
---

# Plan 20-04: Comprehensive Unit Tests for Network, Security, SRE Agent Tools

**93 unit tests + 6 integration triage flow tests covering all 21 tools across 3 domain agents**

## Performance

- **Duration:** 25 min
- **Started:** 2026-04-10
- **Completed:** 2026-04-10
- **Tasks:** 5
- **Files created:** 6
- **Files modified:** 1

## Accomplishments

### Unit Tests (Tasks 01-03)

- **Network agent (31 tests):** 8 test classes covering all 7 tools (query_nsg_rules, query_vnet_topology, query_load_balancer_health, query_peering_status, query_flow_logs, query_expressroute_health, check_connectivity) + ALLOWED_MCP_TOOLS validation + _extract_subscription_id edge cases
- **Security agent (30 tests):** 8 test classes covering all 7 tools (query_defender_alerts, query_keyvault_diagnostics, query_iam_changes, query_secure_score, query_rbac_assignments, query_policy_compliance, scan_public_endpoints) + ALLOWED_MCP_TOOLS validation
- **SRE agent (32 tests):** 9 test classes covering all 7 tools (query_availability_metrics, query_performance_baselines, propose_remediation, query_service_health, query_advisor_recommendations, query_change_analysis, correlate_cross_domain) + _percentile helper + ALLOWED_MCP_TOOLS validation
- Critical resilience tests for `correlate_cross_domain`: partial failure (1 of 4 sub-calls fails) and total failure (all 4 fail) both return success with degraded data

### Integration Triage Flow Tests (Task 04)

- **TestNetworkTriageFlow (2 tests):** NSG misconfiguration diagnosis with envelope validation; cross-domain escalation to compute
- **TestSecurityTriageFlow (2 tests):** Defender alert diagnosis with remediation proposal; cross-domain escalation to network
- **TestSreTriageFlow (2 tests):** Availability degradation with multi-source evidence; VMSS scale remediation requiring approval

### Full Suite Regression Check (Task 05)

- 407 passed, 0 regressions from new code
- 1 pre-existing failure in `test_patch_agent.py` (stale tool count assertion `7` vs actual `8`) — unrelated to this plan

## Task Commits

Each task was committed atomically:

1. **Task 20-04-01: Network agent unit tests** — `9819e3c` (test) — 31 tests, 882 lines
2. **Task 20-04-02: Security agent unit tests** — `341b37b` (test) — 30 tests, 805 lines
3. **Task 20-04-03: SRE agent unit tests** — `33da1f1` (test) — 32 tests, 831 lines
4. **Task 20-04-04: Integration triage flow tests** — `ae8632e` (test) — 6 tests, 201 lines
5. **Task 20-04-05: Full suite verification** — no commit needed (verification only)

## Files Created

- `agents/tests/network/__init__.py` — Empty package init
- `agents/tests/network/test_network_tools.py` — 882 lines, 31 tests across 8 classes
- `agents/tests/security/__init__.py` — Empty package init
- `agents/tests/security/test_security_tools.py` — 805 lines, 30 tests across 8 classes
- `agents/tests/sre/__init__.py` — Empty package init
- `agents/tests/sre/test_sre_tools.py` — 831 lines, 32 tests across 9 classes

## Files Modified

- `agents/tests/integration/test_triage.py` — Added 201 lines: 3 new test classes (TestNetworkTriageFlow, TestSecurityTriageFlow, TestSreTriageFlow) with 6 tests

## Decisions Made

- **MagicMock `.name` attribute workaround:** `MagicMock(name="x")` sets the mock's internal repr name, NOT the `.name` attribute. Created `_mock_with_name()` helper that constructs the mock first, then assigns `.name` as a real attribute. Applied consistently across all 3 test files.
- **3-path testing pattern:** Every `@ai_function` tool gets at minimum: (1) success with realistic SDK response, (2) error when SDK raises exception, (3) error when SDK client is None (import failed). This ensures production resilience.
- **Composite tool isolation:** `correlate_cross_domain` is tested by patching its 4 sub-tool calls (`query_service_health`, `query_change_analysis`, `query_availability_metrics`, `query_advisor_recommendations`) directly, not the underlying SDK clients, providing true unit isolation.
- **Integration tests use real domain models:** Triage flow tests construct actual `TriageDiagnosis` and `RemediationProposal` objects and validate via `validate_envelope()`, testing the full data pipeline.

## Deviations from Plan

None — plan executed exactly as written across all 5 tasks.

## Issues Encountered

- **MagicMock `.name` attribute trap:** Discovered during network test development (6 test failures). Fixed with `_mock_with_name()` helper and proactively applied to security and SRE tests before they hit the same issue.
- **`python` not found:** System uses `python3` instead of `python`. All pytest invocations use `python3 -m pytest`.
- **Pre-existing patch agent test failure:** `test_create_patch_agent_registers_all_seven_tools` asserts `len(tools) == 7` but the agent now has 8 tools. Pre-existing, not caused by this plan.

## User Setup Required

None — all tests use mocks and require no external services or configuration.

## Test Count Impact

| Test File | Tests Added |
|-----------|-------------|
| `agents/tests/network/test_network_tools.py` | +31 |
| `agents/tests/security/test_security_tools.py` | +30 |
| `agents/tests/sre/test_sre_tools.py` | +32 |
| `agents/tests/integration/test_triage.py` | +6 |
| **Total** | **+99** |

---
*Phase: 20-network-security-agent-depth*
*Plan: 20-04*
*Completed: 2026-04-10*
