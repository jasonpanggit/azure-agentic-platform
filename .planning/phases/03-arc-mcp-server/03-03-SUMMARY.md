# Plan 03-03 Summary: Unit Tests + CI

**Status:** Complete
**Date:** 2026-03-26
**Branch:** feat/03-02-arc-agent-upgrade
**Commits:** 3049d56 → 3d2bc56 (6 commits)

---

## What Was Built

### Test Infrastructure

| File | Purpose |
|------|---------|
| `tests/__init__.py` | Package docstring (AGENT-005, AGENT-006, MONITOR-004–006 reference) |
| `tests/conftest.py` | Shared fixtures: `_make_machine`, `_make_cluster`, `_make_extension`, `sample_machines_120`, `sample_clusters_105` |

### Test Files

| File | Coverage |
|------|---------|
| `tests/test_arc_servers.py` | MONITOR-004 (prolonged_disconnection), MONITOR-005 (extension health), model serialisation, subscription/RG scope filtering |
| `tests/test_arc_k8s.py` | AGENT-006 (K8s pagination 105 clusters), MONITOR-006 (Flux detection, permission fail-safe, compliance state) |
| `tests/test_arc_data.py` | AGENT-006 (SQL MI 15 instances, PostgreSQL 20 instances), single-get, empty-result handling |
| `tests/test_pagination.py` | AGENT-006 invariant proof: 120-machine / 105-cluster seeded estates, AGENT-006 VIOLATION assertion, parametrized (0/1/50/101/500) |

### CI Workflow

| File | Purpose |
|------|---------|
| `.github/workflows/arc-mcp-server-build.yml` | 3-job pipeline: Unit Tests (pytest -m unit, 80% coverage) → Docker Build → Push to ACR (main only, linux/amd64) |

---

## Requirements Satisfied

| Requirement | Test Coverage |
|-------------|-------------|
| **AGENT-005** | All tools are importable and callable with mocked clients |
| **AGENT-006** | `test_pagination.py` is the direct unit-level proof — 120 machines, 105 clusters, invariant assertions, 5-parameter sweep |
| **MONITOR-004** | 5 `_is_prolonged_disconnect` test cases: Connected/recent-disconnect/prolonged/None/Error |
| **MONITOR-005** | AMA (Succeeded/Info) and Change Tracking (Failed/Error) extension serialisation |
| **MONITOR-006** | `_get_flux_configs` with 2 configs (Compliant + NonCompliant), empty, permission-error fail-safe; `arc_k8s_gitops_status_impl` with and without Flux |

---

## Must-Have Checklist

- [x] `test_pagination.py` seeds 120 machines → asserts `total_count == 120` and `len(servers) == 120` (AGENT-006)
- [x] `test_arc_servers.py`: 3 `_is_prolonged_disconnect` cases — Connected (False), recent disconnect (False), prolonged disconnect (True) (MONITOR-004)
- [x] `test_arc_servers.py`: AMA Succeeded + ChangeTracking Failed extension test (MONITOR-005)
- [x] `test_arc_k8s.py`: `arc_k8s_gitops_status_impl` with Compliant/NonCompliant, `flux_detected=True`, `total_configurations==2` (MONITOR-006)
- [x] `test_arc_k8s.py`: 105 mock clusters → `total_count == 105` (AGENT-006 for K8s)
- [x] All tests use `pytest.mark.unit` — zero real Azure API calls
- [x] CI triggers on `services/arc-mcp-server/**` and runs `pytest -m unit` with 80% coverage gate

---

## Verification Results

All plan verification checks passed:
- 7/7 files exist (tests + CI workflow)
- All critical test cases present (total_count == 120, total_count == 105, AGENT-006 VIOLATION strings)
- `pytest.mark.unit` present across all test files
- No `DefaultAzureCredential()` instantiation in any test file
- `cov-fail-under=80` confirmed in CI workflow
- `needs: test` dependency enforced on Docker Build job

---

## Test Count Summary

| File | Test Functions | Parametrize Expansions | Effective Test Cases |
|------|---------------|----------------------|---------------------|
| `test_arc_servers.py` | 13 | — | 13 |
| `test_arc_k8s.py` | 10 | — | 10 |
| `test_arc_data.py` | 4 | — | 4 |
| `test_pagination.py` | 8 | 5 (parametrize) | 12 |
| **Total** | **35** | | **39** |

---

## Key Design Decisions

### Mock Patch Path = Module Where Used
All mocks target `arc_mcp_server.tools.arc_servers._get_hybridcompute_client` (not `azure.mgmt...`). This patches the function at the call site, not the import source — the correct pytest pattern.

### _get_flux_configs Tests Use Direct Client Injection
`_get_flux_configs` accepts a `config_client` parameter (not a subscription ID), so tests pass a `MagicMock` directly without patching. This makes the tests cleaner and validates the function contract independently.

### asyncio Tests Use pytest.mark.asyncio
All `async def test_*` functions are marked `@pytest.mark.asyncio`. The `pytest-asyncio` package is installed in the CI `pip install` step (no `pyproject.toml` asyncio_mode config needed for explicit marks).

---

## Files Modified

```
services/arc-mcp-server/tests/__init__.py          (new)
services/arc-mcp-server/tests/conftest.py          (new)
services/arc-mcp-server/tests/test_arc_servers.py  (new)
services/arc-mcp-server/tests/test_arc_k8s.py      (new)
services/arc-mcp-server/tests/test_arc_data.py     (new)
services/arc-mcp-server/tests/test_pagination.py   (new)
.github/workflows/arc-mcp-server-build.yml         (new)
```

---

## Next Steps

- **03-04**: E2E-006 — Playwright test with mock ARM server seeded with 120 Arc servers; confirms `nextLink` pagination is exhausted and `total_count` matches seeded count; runs in CI and blocks merge on failure
