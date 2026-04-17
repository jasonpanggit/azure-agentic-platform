# Phase 69-1 Plan: Simulation Tab

## Goal
Give operators a simulation panel to trigger realistic incident scenarios against the platform, validating that agents respond correctly, routing works, and the detection-to-triage pipeline is healthy end-to-end.

## Requirements
- 10 predefined simulation scenarios covering all domains
- Dry-run mode (validate without injecting)
- Inject real incidents with `[SIMULATION]` prefix and `sim-` ID prefix
- Track run history in Cosmos
- Domain-colored scenario cards in the UI
- Run history table with status badges

## Implementation
- Backend: `simulation_endpoints.py` with list/run/history endpoints
- Frontend: `SimulationTab.tsx` with scenario grid, run modal, history table
- Proxy routes: 3 routes under `/api/proxy/simulations/`
- DashboardPanel: FlaskConical icon tab

## Tests
21 tests in `test_simulation_endpoints.py`
