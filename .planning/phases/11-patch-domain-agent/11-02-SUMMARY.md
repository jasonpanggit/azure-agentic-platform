# Plan 11-02 Summary: Orchestrator Routing + Integration Tests

**Status:** COMPLETE
**Date:** 2026-03-30
**Commits:** 4 atomic commits

---

## Tasks Completed

### 11-02-01: Add patch keywords to QUERY_DOMAIN_KEYWORDS
- Added `"patch"` entry to `QUERY_DOMAIN_KEYWORDS` in `agents/shared/routing.py`
- 12 keywords: patch, patches, patching, update manager, windows update, security patch, patch compliance, patch status, missing patches, pending patches, kb article, hotfix
- Positioned after "arc" and before "compute" (D-12)
- Generic "update"/"updates" deliberately excluded
- `QUERY_DOMAIN_KEYWORDS` now has 6 entries (was 5)

### 11-02-02: Wire patch into orchestrator
- `DOMAIN_AGENT_MAP`: added `"patch": "patch-agent"` (7 entries total)
- `RESOURCE_TYPE_TO_DOMAIN`: added `"microsoft.maintenance": "patch"` (12 entries total)
- System prompt: added patch-agent to Domain→agent mapping and Type B conversational routing
- `create_orchestrator()`: registered patch `AgentTarget` with `PATCH_AGENT_ID` env var
- Updated all comments/docstrings from "6 domain" to "7 domain"

### 11-02-03: Update existing integration tests
- Renamed `test_domain_agent_map_has_all_six_domains` → `test_domain_agent_map_has_all_seven_domains`
- Added `test_classify_maintenance_resource` (Microsoft.Maintenance → patch)
- Added `test_classify_patch_conversational_variants` (4 parametrized cases)
- Added `test_classify_generic_update_does_not_route_to_patch` (D-12 exclusion)
- All 23 integration tests pass

### 11-02-04: Focused routing unit tests
- Created `agents/tests/patch/test_routing.py` with 24 tests in 4 classes:
  - `TestQueryDomainKeywordsStructure` (6 tests): entry count, ordering, keyword count, D-12 compliance
  - `TestClassifyPatchKeywords` (12 tests): 9 patch routing + 3 "update" exclusion
  - `TestOtherDomainsUnaffected` (5 tests): compute/arc/storage/network/security unchanged
  - `TestPatchPrecedence` (1 test): patch wins over compute when both match
- All 24 routing unit tests pass

---

## Verification Results

| Check | Result |
|---|---|
| `QUERY_DOMAIN_KEYWORDS` has 6 entries with "patch" as 2nd | PASS |
| `DOMAIN_AGENT_MAP` has 7 entries including "patch" | PASS |
| `RESOURCE_TYPE_TO_DOMAIN` has 12 entries including "microsoft.maintenance" | PASS |
| System prompt contains patch routing rules | PASS |
| `create_orchestrator()` registers patch AgentTarget | PASS |
| `PATCH_AGENT_ID` env var referenced | PASS |
| Query "show patch compliance" routes to "patch" | PASS |
| Query "update my vm size" does NOT route to "patch" | PASS |
| Integration tests: 23/23 pass | PASS |
| Routing unit tests: 24/24 pass | PASS |
| **Total tests: 47/47 pass** | **PASS** |

---

## Files Modified

| File | Action |
|---|---|
| `agents/shared/routing.py` | Modified — added patch entry to QUERY_DOMAIN_KEYWORDS |
| `agents/orchestrator/agent.py` | Modified — DOMAIN_AGENT_MAP, RESOURCE_TYPE_TO_DOMAIN, system prompt, AgentTarget |
| `agents/tests/integration/test_handoff.py` | Modified — renamed test, added 3 new test methods |
| `agents/tests/patch/test_routing.py` | Created — 24 focused routing unit tests |

---

## Requirements Addressed

| REQ-ID | How Satisfied |
|---|---|
| TRIAGE-001 | Orchestrator classifies patch incidents via RESOURCE_TYPE_TO_DOMAIN and keyword routing |
| AGENT-001 | Patch agent registered as AgentTarget in HandoffOrchestrator |
| AGENT-002 | Patch routing uses existing typed envelope flow (no envelope changes needed) |
