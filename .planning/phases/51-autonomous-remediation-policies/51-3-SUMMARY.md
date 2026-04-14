# Summary: Plan 51-3 — Learning Suggestion Engine

## Status: COMPLETE

## Tasks Completed

### 51-3-01 — Add policy_suggestions Cosmos container to Terraform
- Added `azurerm_cosmosdb_sql_container.policy_suggestions` to `terraform/modules/databases/cosmos.tf`
- Partition key: `/action_class` | TTL: 2592000s (30 days) | Consistent indexing
- Added `cosmos_policy_suggestions_container_name` output to `terraform/modules/databases/outputs.tf`
- `terraform fmt -check` passes on both files
- **Commit:** `1d2df7b`

### 51-3-02 — Create suggestion_engine.py with pattern detection
- Created `services/api-gateway/suggestion_engine.py` (375 lines)
- `run_suggestion_sweep`: queries `remediation_audit` for HITL-approved executions (excludes `auto_approved_by_policy`), groups by `proposed_action`, creates suggestions when ≥5 approvals + 0 rollbacks
- `run_suggestion_sweep_loop`: asyncio background task, 6h interval, mirrors `run_pattern_analysis_loop` pattern
- `get_pending_suggestions`: returns non-dismissed, unconverted suggestions
- `dismiss_suggestion`: sets `dismissed=True` via `replace_item`
- `convert_suggestion_to_policy`: sets `converted_to_policy_id` via `replace_item`
- All Cosmos I/O runs in executor threads (non-blocking)
- **Commit:** `25bded9`

### 51-3-03 — Add suggestion API endpoints to admin_endpoints.py
- Imported `get_pending_suggestions`, `dismiss_suggestion`, `convert_suggestion_to_policy` from `suggestion_engine`
- `GET /api/v1/admin/policy-suggestions` — lists pending suggestions, requires `verify_token`
- `POST /api/v1/admin/policy-suggestions/{id}/dismiss` — marks dismissed, 404 on failure
- `POST /api/v1/admin/policy-suggestions/{id}/convert` — creates policy in PostgreSQL + links suggestion in Cosmos (best-effort)
- **Commit:** `eb662b8`

### 51-3-04 — Start suggestion sweep loop in main.py lifespan
- Added import of `SUGGESTION_SWEEP_INTERVAL_SECONDS` and `run_suggestion_sweep_loop`
- Created `asyncio.Task` in lifespan startup (only when `cosmos_client` is available)
- Cancels cleanly on shutdown with `CancelledError` handling
- Startup log: `"startup: suggestion sweep loop started | interval=%ds"`
- Shutdown log: `"shutdown: suggestion sweep loop cancelled"`
- **Commit:** `74fc282`

### 51-3-05 — Write unit tests for suggestion engine
- Created `services/api-gateway/tests/test_suggestion_engine.py` (278 lines, 7 tests)
- `test_sweep_no_qualifying_patterns` — < 5 records → no suggestions
- `test_sweep_creates_suggestion` — 5 HITL approvals + 0 rollbacks → suggestion with correct fields
- `test_sweep_skips_if_rollback_present` — 1 DEGRADED → no suggestion
- `test_sweep_skips_auto_approved` — verifies `auto_approved_by_policy` exclusion in query text
- `test_get_pending_suggestions` — confirms `dismissed=false` + `converted_to_policy_id=null` filter
- `test_dismiss_suggestion_success` — `dismissed=True` set via `replace_item`
- `test_convert_suggestion_to_policy` — `converted_to_policy_id` linked via `replace_item`
- All 7 tests pass in 0.03s
- **Commit:** `392b9e9`

## Verification Results

| Check | Result |
|---|---|
| `terraform fmt -check modules/databases/cosmos.tf` | ✅ Pass |
| `terraform fmt -check modules/databases/outputs.tf` | ✅ Pass |
| `pytest test_suggestion_engine.py -v` | ✅ 7/7 pass |
| `grep -c "policy_suggestions" cosmos.tf` | ✅ 2 (container + comment) |
| AST parse on suggestion_engine.py | ✅ Pass |
| AST parse on admin_endpoints.py | ✅ Pass |
| AST parse on main.py | ✅ Pass |

## Must-Haves Checklist

- [x] Cosmos `policy_suggestions` container with `/action_class` partition key and 30-day TTL
- [x] `suggestion_engine.py` sweep logic: 5+ HITL approvals + 0 rollbacks → suggestion
- [x] Auto-approved records excluded from suggestion counts
- [x] 3 suggestion API endpoints (list, dismiss, convert) in admin_endpoints.py
- [x] Background sweep loop started in main.py lifespan with cancellation on shutdown
- [x] ≥6 unit tests covering sweep logic and API (7 tests delivered)

## Files Modified

| File | Change |
|---|---|
| `terraform/modules/databases/cosmos.tf` | Added `policy_suggestions` container |
| `terraform/modules/databases/outputs.tf` | Added `cosmos_policy_suggestions_container_name` output |
| `services/api-gateway/suggestion_engine.py` | **New file** — full suggestion engine |
| `services/api-gateway/admin_endpoints.py` | Added 3 suggestion endpoints + imports |
| `services/api-gateway/main.py` | Added suggestion sweep loop to lifespan |
| `services/api-gateway/tests/test_suggestion_engine.py` | **New file** — 7 unit tests |
