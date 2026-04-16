# Phase 58-1 Plan: IaC Drift Detection

## Goal
Continuously detect when live Azure infrastructure deviates from Terraform state.

## Files to Create
1. `services/api-gateway/drift_detector.py` — DriftDetector service class + pure helpers
2. `services/api-gateway/drift_endpoints.py` — FastAPI router: GET /findings, POST /scan, GET /scan/{job_id}, GET /findings/{id}/fix
3. Register `drift_router` in `main.py`
4. `services/web-ui/components/DriftTab.tsx` — findings table + scan trigger + propose-fix
5. `services/web-ui/app/api/proxy/drift/findings/route.ts` — proxy
6. `services/web-ui/app/api/proxy/drift/scan/route.ts` — proxy
7. Register DriftTab in `DashboardPanel.tsx` (TabId union, TAB_GROUPS, panel render)
8. `services/api-gateway/tests/test_drift_detector.py` — ≥19 pytest tests

## Severity Model
- CRITICAL = resource deleted
- HIGH = critical attributes (sku, location, network_profile, etc.)
- MEDIUM = numeric/boolean attribute changes
- LOW = tags/metadata
