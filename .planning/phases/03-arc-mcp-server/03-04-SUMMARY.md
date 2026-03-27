# Plan 03-04 Summary: Integration Tests + E2E-006

**Status:** Complete
**Date:** 2026-03-26
**Branch:** feat/03-02-arc-agent-upgrade
**Commits:** ee232ac → 268379b (4 commits)

---

## What Was Built

### Integration Test Infrastructure

| File | Purpose |
|------|---------|
| `agents/tests/integration/__init__.py` | Package docstring identifying integration test scope |
| `agents/tests/integration/test_arc_triage.py` | Full Arc triage workflow tests (TRIAGE-006, MONITOR-004, AGENT-006) |

### Playwright E2E Test

| File | Purpose |
|------|---------|
| `e2e/arc-mcp-server.spec.ts` | E2E-006 pagination test with mock ARM server seeding (120 Arc servers) |

### Deployment Verification

| File | Purpose |
|------|---------|
| `scripts/verify-arc-connectivity.sh` | Arc MCP Server connectivity + tools/list + arc_servers_list verification script |

### Phase Completion Checklist

| File | Purpose |
|------|---------|
| `docs/verification/phase-3-checklist.md` | Manual verification checklist covering all 6 Phase 3 success criteria |

---

## Requirements Satisfied

| Requirement | How |
|-------------|-----|
| **TRIAGE-006** | `test_arc_triage_workflow_produces_diagnosis` verifies full connectivity → extension health → GitOps → TriageDiagnosis sequence with all required fields |
| **MONITOR-004** | `test_prolonged_disconnection_detection` + `test_prolonged_disconnection_triggers_alert` verify disconnection flagging and `ArcServerProlongedDisconnection` alert payload structure |
| **AGENT-006** | `test_total_count_matches_servers_list` + `test_extension_health_total_count` enforce total_count invariant in all list responses |
| **E2E-006** | `arc-mcp-server.spec.ts` verifies `total_count >= 100`, `len(servers) == total_count`, unique names (no duplicate pages) via mock ARM server |

---

## Must-Have Checklist

- [x] `test_arc_triage_workflow_produces_diagnosis` calls all 5 TRIAGE-006 steps, asserts TriageDiagnosis has `confidence_score`, `evidence`, `activity_log_findings`
- [x] `test_prolonged_disconnection_detection` verifies `last_status_change` > 1h threshold triggers `prolonged_disconnection=True` (MONITOR-004)
- [x] `test_prolonged_disconnection_triggers_alert` asserts alert payload has `detection_rule: "ArcServerProlongedDisconnection"` and all required fields
- [x] E2E test verifies `total_count >= 100` and `total_count == len(servers)` (E2E-006)
- [x] E2E test covers all 9 required Arc MCP Server tools in `tools/list` check
- [x] All integration tests use `pytest.mark.integration` — NOT `pytest.mark.unit`
- [x] `verify-arc-connectivity.sh` is executable, uses `set -euo pipefail`, checks all 9 tools
- [x] Phase 3 checklist covers all 6 SC items with checkboxes and verification commands

---

## Verification Results

All plan verification checks passed:
- 5/5 required files exist
- Script is executable (`chmod +x` applied)
- No `pytest.mark.unit` in integration test file (excluded from fast CI run)
- All 7 Phase 3 requirements covered across `.planning/phases/03-arc-mcp-server/`
- E2E spec references all 9 required Arc MCP Server tools
- Phase 3 checklist has exactly 6 SC headers with checkboxes

---

## Integration Test Count

| File | Test Functions | Marks |
|------|---------------|-------|
| `test_arc_triage.py` | 6 | `pytest.mark.integration` (+ `asyncio` for one) |
| **Total** | **6** | |

---

## E2E Test Count

| File | Test Cases |
|------|-----------|
| `e2e/arc-mcp-server.spec.ts` | 5 (`arc_servers_list` pagination, `arc_k8s_list` pagination, full triage flow, health check, tool discovery) |

---

## Key Design Decisions

### Integration Tests Excluded from Fast Unit CI
`pytest.mark.integration` is required on all tests in `agents/tests/integration/`. The CI unit test job (03-03's `arc-mcp-server-build.yml`) runs `-m unit`, excluding integration tests. A separate integration job would run `-m integration` against a deployed environment.

### E2E Test Uses AZURE_ARM_BASE_URL Override
The Playwright E2E test environment points `ARC_MCP_SERVER_URL` at a local or CI-deployed Arc MCP Server that was started with `AZURE_ARM_BASE_URL` pointing to a mock ARM server. This avoids real Azure credentials and costly Arc estate provisioning in CI. `ARC_SEEDED_COUNT` (default 120) configures the expected total.

### Phase 3 Checklist as Operator Artifact
`docs/verification/phase-3-checklist.md` is designed to be printed/shared with operators and reviewers, not just developers. Each SC item is self-contained with copy-pasteable bash commands and clear expected output.

---

## Files Created

```
agents/tests/integration/__init__.py           (updated)
agents/tests/integration/test_arc_triage.py    (new)
e2e/arc-mcp-server.spec.ts                     (new)
scripts/verify-arc-connectivity.sh             (new, executable)
docs/verification/phase-3-checklist.md         (new)
```

---

## Phase 3 Complete

All 4 plans of Phase 3: Arc MCP Server are now complete:

| Plan | Title | Status |
|------|-------|--------|
| 03-01 | Arc MCP Server — Core + Terraform | ✅ Complete |
| 03-02 | Arc Agent Upgrade | ✅ Complete |
| 03-03 | Unit Tests + CI | ✅ Complete |
| 03-04 | Integration Tests + E2E-006 | ✅ Complete |

**Phase 3 unblocks Phase 5 Arc paths:** REMEDI-008 (GitOps Remediation) and TRIAGE-006 (Arc-specific triage) are now available for Phase 5 implementation.
