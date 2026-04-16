# Phase 58-1 Summary: IaC Drift Detection

## What Was Built

### Backend
- **`drift_detector.py`** — `DriftDetector` class with:
  - `_load_tfstate()` — downloads `.tfstate` from Azure Blob Storage (lazy SDK guard)
  - `parse_tfstate_resources()` — parses managed resources from tfstate JSON, skips data sources
  - `classify_drift_severity()` — pure function: CRITICAL (deleted) > HIGH (sku/location/network) > MEDIUM (numeric) > LOW (tags)
  - `compare_attributes()` — flattened attribute diff, produces `DriftFinding` list
  - `run_scan()` — full scan loop, saves findings to Cosmos `drift_findings`
  - `list_findings()` — queries Cosmos with severity/resource_type/limit filters
  - `propose_terraform_fix()` — returns HCL diff string per finding

- **`drift_endpoints.py`** — FastAPI router:
  - `GET /api/v1/drift/findings` — list with ?severity=, ?resource_type=, ?limit=
  - `POST /api/v1/drift/scan` — async scan job, returns job_id
  - `GET /api/v1/drift/scan/{job_id}` — poll status
  - `GET /api/v1/drift/findings/{finding_id}/fix` — propose HCL fix

- **`main.py`** — `drift_router` registered via `app.include_router(drift_router)`

### Frontend
- **`DriftTab.tsx`** — findings table with 8 columns, SeverityBadge (CSS semantic tokens), "Trigger Scan" button, "Propose Fix" per row (inline diff), empty state, loading skeletons, auto-refresh every 5 minutes
- **`app/api/proxy/drift/findings/route.ts`** — GET proxy with AbortSignal.timeout(15000)
- **`app/api/proxy/drift/scan/route.ts`** — POST proxy with AbortSignal.timeout(15000)
- **`DashboardPanel.tsx`** — `drift` added to TabId union, TAB_GROUPS (Security & compliance group), panel render

### Tests
- **`tests/test_drift_detector.py`** — 19 tests covering:
  - `test_parse_tfstate_resources_*` (4 tests)
  - `test_drift_finding_severity_*` (5 tests)
  - `test_no_drift_when_state_matches`
  - `test_drift_detected_when_location_differs`
  - `test_findings_api_returns_list`
  - `test_findings_api_returns_empty_when_no_cosmos`
  - `test_run_scan_returns_metadata_when_tfstate_unavailable`
  - `test_propose_terraform_fix_*` (2 tests)
  - `test_extract_subscription_id*` (2 tests)
  - `test_flatten_dict_nested`

## Verification Results

### Python tests
```
19 passed, 3 warnings in 0.03s
```
All 19 tests green.

### TypeScript
```
2 pre-existing errors (OpsTab.test.tsx, SecurityPostureTab.tsx) — not introduced by this phase
0 new errors
```

## Patterns Followed
- Lazy SDK imports with `try/except ImportError` + `None` fallback
- `start_time = time.monotonic()` at function entry, `duration_ms` in all returns
- Tool functions never raise — structured error dicts returned
- CSS semantic tokens only (`var(--accent-red)`, `var(--accent-yellow)`, etc.)
- `runtime='nodejs'`, `dynamic='force-dynamic'`, `AbortSignal.timeout(15000)` in all proxy routes
