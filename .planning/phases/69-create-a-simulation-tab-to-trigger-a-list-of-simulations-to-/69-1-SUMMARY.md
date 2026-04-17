# Phase 69-1 Summary: Simulation Tab

## Status: ✅ Complete

## What Was Built

### Backend (`services/api-gateway/simulation_endpoints.py`)
- 10 predefined scenarios: vm-high-cpu, storage-latency, nsg-blocked-traffic, vm-disk-full, keyvault-access-denied, arc-agent-offline, database-connection-pool, aks-node-notready, sev0-cascade, cost-anomaly
- `GET /api/v1/simulations` — list all scenarios
- `POST /api/v1/simulations/run` — trigger simulation (dry_run supported), injects via httpx POST /api/v1/incidents, persists run record to Cosmos `simulation_runs` container
- `GET /api/v1/simulations/runs` — run history with optional scenario_id filter
- `GET /api/v1/simulations/runs/{run_id}` — specific run details

### Frontend (`services/web-ui/components/SimulationTab.tsx`)
- 2-column scenario grid with DomainBadge (CSS token per-domain colors) and SeverityBadge
- Run modal with optional target_resource/resource_group, dry_run checkbox, result display
- Run history table: status badges (triggered=blue, validated=grey, injection_failed=red)
- Auto-refresh 1.5s after successful run
- State-based notification banner (auto-dismisses after 7s)
- No-subscription warning when none selected

### Proxy routes (3 files)
- `simulations/route.ts`, `simulations/run/route.ts`, `simulations/runs/route.ts`

### DashboardPanel.tsx
- Added `'simulations'` to TabId, FlaskConical icon, lazy render

## Tests
21/21 passing in `test_simulation_endpoints.py`
