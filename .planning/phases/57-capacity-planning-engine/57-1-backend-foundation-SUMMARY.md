---
plan: 57-1
phase: 57-capacity-planning-engine
status: complete
executed_at: 2026-04-16
---

# Summary: Plan 57-1 — Backend Foundation

## What Was Built

Core capacity planning module for the Azure Agentic Platform — pure-Python linear
regression engine, Cosmos snapshot persistence, quota headroom collection (Compute +
Network + Storage), ARG-based IP address space headroom, daily sweep loop, and 34
unit tests.

## Tasks Completed

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `capacity_planner.py` skeleton with linear regression engine | ✅ | 662ba4f |
| 2 | `get_subscription_quota_headroom()` (Compute + Network + Storage) | ✅ | 662ba4f |
| 3 | `get_ip_address_space_headroom()` via ARG bulk query | ✅ | 662ba4f |
| 4 | Daily sweep loop + `main.py` lifespan wiring | ✅ | 8a60af7 |
| 5 | Cosmos `capacity_snapshots` container (Terraform) | ✅ | efdfa68 |
| 6 | `azure-mgmt-containerservice` in requirements.txt | ✅ | pre-existing (>=21.0.0 + >=41.0.0) |
| 7 | 34 unit tests in `tests/test_capacity_planner.py` | ✅ | 07412f5 |

## Files Modified / Created

| File | Change |
|------|--------|
| `services/api-gateway/capacity_planner.py` | Created (671 lines) |
| `services/api-gateway/main.py` | Added import + lifespan sweep task (+25 lines) |
| `terraform/modules/databases/cosmos.tf` | Added `capacity_snapshots` container (+18 lines) |
| `tests/test_capacity_planner.py` | Created (413 lines, 34 tests) |

## Acceptance Criteria Met

- [x] `_linear_regression` returns `(slope, intercept, r_squared)` correctly for known datasets
- [x] `_days_to_exhaustion` returns `None` for slope ≤ 0, correctly projects days for positive slope, caps at 365
- [x] `get_subscription_quota_headroom()` calls Compute + Network + Storage, filters zero-limit, never raises
- [x] `get_ip_address_space_headroom()` uses ARG bulk query, `available = total - 5 - ip_config_count`
- [x] Daily sweep upserts snapshots to Cosmos `capacity_snapshots`
- [x] Cosmos container provisioned with `/subscription_id` partition key and 400-day TTL (34560000s)
- [x] 34 passing unit tests (≥ 30 required)

## Test Results

```
34 passed in 0.09s
```

## Design Decisions

- **No numpy/statsmodels**: pure-Python regression keeps the container image lean and avoids
  heavy scientific dependencies; linear regression is appropriate for daily quota snapshots
  (per RESEARCH.md §3.2 — series too short for seasonal decomposition).
- **Three SDK categories**: Compute + Network + Storage quota collected in a single call;
  missing SDKs produce warnings in response, not exceptions.
- **ARG for IP space**: single bulk query avoids O(n) per-VNet SDK iteration;
  `available = total - 5 (Azure reserved) - ip_config_count` matches Azure documentation.
- **Confidence interval**: ±90% CI stored as percentage of intercept for frontend display
  without requiring frontend math.
- **Sweep pattern**: mirrors `run_forecast_sweep_loop` (sleep-first, run_in_executor for
  blocking SDK calls, CancelledError re-raised for clean shutdown).
