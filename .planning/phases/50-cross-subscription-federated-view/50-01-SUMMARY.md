---
phase: 50-cross-subscription-federated-view
plan: "01"
status: complete
started: "2026-04-14"
completed: "2026-04-14"
commits:
  - f07b3dd
  - 9e1d718
tests_added: 7
tests_total: 892
---

# 50-01 Summary: Subscription Registry

## What Was Built

### Task 1: SubscriptionRegistry class (TDD)

Created `services/api-gateway/subscription_registry.py` — the subscription auto-discovery foundation for the cross-subscription federated view.

**Class: `SubscriptionRegistry`**

| Method | Purpose |
|--------|---------|
| `discover()` | Queries ARG with KQL to list all Enabled subscriptions accessible to the managed identity |
| `sync_to_cosmos()` | Upserts discovered subscriptions to Cosmos `subscriptions` container; no-op when `cosmos_client=None` |
| `get_all_ids()` | Returns `List[str]` of subscription IDs from in-memory cache (O(1)) |
| `get_all()` | Returns `List[Dict[str, str]]` of `{id, name}` records from cache |
| `full_sync()` | Async: discover → update cache → persist to Cosmos |
| `run_refresh_loop(interval_seconds=6*3600)` | Background task: `full_sync()` on startup then every 6 hours |

**Design decisions:**
- `discover()` returns `[]` (non-fatal) when `azure-mgmt-resourcegraph` is not installed — graceful degradation in dev/test
- `sync_to_cosmos()` silently no-ops when `cosmos_client=None` — works without Cosmos in test
- `run_refresh_loop()` re-raises `asyncio.CancelledError` to cooperate with task cancellation; logs but never propagates other exceptions
- ARG query scoped to tenant (no subscription filter) to find all accessible subscriptions

**Tests: 7/7 pass** (`services/api-gateway/tests/test_subscription_registry.py`)
- `TestDiscover`: ARG success path, ImportError fallback
- `TestSync`: Cosmos upsert fields validated, no-op when no cosmos
- `TestGetAllIds`: cache-backed reads, empty-before-sync
- `TestRefreshLoop`: calls `full_sync()` twice, verifies `asyncio.sleep` awaited

### Task 2: Cosmos container + startup wiring + endpoint

**Terraform** (`terraform/modules/databases/cosmos.tf`):
- Added `azurerm_cosmosdb_sql_container "subscriptions"` with `partition_key_paths = ["/subscription_id"]`, `partition_key_version = 2`, `default_ttl = -1` (no expiry)

**main.py startup wiring:**
- Imports `SubscriptionRegistry` at module level
- Creates `app.state.subscription_registry` after `cosmos_client` init
- Calls `await app.state.subscription_registry.full_sync()` synchronously at startup (non-fatal on error)
- Launches `asyncio.create_task(run_refresh_loop(interval_seconds=6*3600))` for background refresh
- `TopologyClient` now uses `app.state.subscription_registry.get_all_ids()` as primary subscription source; falls back to `SUBSCRIPTION_IDS` env var when registry returns empty

**New endpoint:**
```
GET /api/v1/subscriptions
→ {"subscriptions": [{"id": "sub-abc", "name": "My Subscription"}, ...]}
```
Returns empty list gracefully when registry is not initialized or no subscriptions found.

## Verification

```
✅ 7/7 subscription registry tests pass
✅ azurerm_cosmosdb_sql_container "subscriptions" defined with /subscription_id partition key
✅ main.py imports SubscriptionRegistry
✅ app.state.subscription_registry created in lifespan
✅ full_sync() called at startup
✅ run_refresh_loop() launched as background task
✅ GET /api/v1/subscriptions endpoint defined
✅ TopologyClient uses registry IDs with env var fallback
✅ 885/885 existing tests pass (0 regressions)
```

## Files Modified

| File | Change |
|------|--------|
| `services/api-gateway/subscription_registry.py` | **Created** — SubscriptionRegistry class |
| `services/api-gateway/tests/test_subscription_registry.py` | **Created** — 7 unit tests |
| `terraform/modules/databases/cosmos.tf` | **Modified** — added subscriptions container |
| `services/api-gateway/main.py` | **Modified** — import, startup wiring, endpoint |

## Requirements Satisfied

- `CROSS-SUB-001`: Registry foundation — auto-discovers all accessible subscriptions via ARG
- `GET /api/v1/subscriptions` returns discovered subscriptions (name + id)
- Registry bootstraps at startup; 6h background refresh
- `app.state.subscription_registry.get_all_ids()` provides `List[str]` to all federated endpoints
