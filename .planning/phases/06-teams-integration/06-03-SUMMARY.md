# Plan 06-03 Summary: API Gateway Changes + Cross-Surface Thread Sharing

## Result: COMPLETE

All 5 tasks executed successfully with TDD (RED→GREEN) for every implementation change.

---

## Tasks Completed

| Task | Title | Tests Added | Status |
|------|-------|-------------|--------|
| 06-03-01 | Add thread_id and user_id to ChatRequest model | 4 | Complete |
| 06-03-02 | Support thread continuation in chat.py | 4 | Complete |
| 06-03-03 | Add GET /api/v1/approvals endpoint | 3 | Complete |
| 06-03-04 | Accept thread_id in approval body (Action.Execute) | 4 | Complete |
| 06-03-05 | Refactor teams_notifier.py to bot internal endpoint | 7 | Complete |

**Total new tests: 22**
**Full api-gateway test suite: 71 passed, 2 skipped, 0 failures**

---

## Changes Made

### `services/api-gateway/models.py`
- `ChatRequest`: Added `thread_id: Optional[str]` (TEAMS-004) and `user_id: Optional[str]` (D-07)
- `ApprovalAction`: Added `thread_id: Optional[str]` (TEAMS-003 Action.Execute)

### `services/api-gateway/chat.py`
- `create_chat_thread()`: Now supports three modes:
  1. `thread_id` provided → continue existing thread (skip creation)
  2. `incident_id` provided → look up thread from Cosmos DB
  3. Neither → create new thread (existing default)
- Added `_lookup_thread_by_incident()` helper for Cosmos DB lookup
- `effective_user_id = request.user_id or user_id` for D-07

### `services/api-gateway/main.py`
- `start_chat()`: Uses `payload.user_id or token.get("sub")` for identity precedence
- `approve_proposal()` / `reject_proposal()`: Accept `thread_id` from body or query param; return 400 if missing
- Added `GET /api/v1/approvals` endpoint (before `/{approval_id}` to avoid path conflicts)
- Imported `list_approvals_by_status`

### `services/api-gateway/approvals.py`
- Added `list_approvals_by_status()` with cross-partition Cosmos DB query (TEAMS-005)

### `services/api-gateway/teams_notifier.py`
- Complete rewrite: `TEAMS_WEBHOOK_URL` → `TEAMS_BOT_INTERNAL_URL`
- Removed `_build_adaptive_card()` (card rendering moved to TypeScript bot)
- Added generic `notify_teams()` dispatcher
- Added `post_alert_card()` and `post_outcome_card()` wrappers
- Maintained `post_approval_card()` signature for backward compatibility

### Test Files
- `test_chat_endpoint.py`: +8 tests (4 model, 4 thread continuation)
- `test_approval_lifecycle.py`: +7 tests (3 pending listing, 4 body thread_id)
- `test_teams_notifier.py`: Created with 7 tests (new file)

---

## Requirements Addressed

| REQ-ID | Description | How |
|--------|-------------|-----|
| TEAMS-003 | Approval via Teams Adaptive Cards | thread_id in ApprovalAction body for Action.Execute |
| TEAMS-004 | Cross-surface thread sharing | ChatRequest.thread_id, _lookup_thread_by_incident(), 3-mode chat |
| TEAMS-005 | Escalation scheduler support | GET /api/v1/approvals?status=pending endpoint |
| D-04 | teams_notifier superseded by bot | Refactored to call bot internal notify endpoint |
| D-07 | Teams operator identity | ChatRequest.user_id, effective_user_id precedence |
| D-11 | Bot internal notify endpoint | POST /teams/internal/notify integration |

---

## Backward Compatibility

All changes are backward-compatible:
- ChatRequest `thread_id` and `user_id` default to `None`
- Approval endpoints still accept `thread_id` as query parameter
- `post_approval_card()` maintains same function signature
- Web UI continues to work without modification

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| body.thread_id takes precedence over query param | Action.Execute sends data in card body; body is more explicit |
| GET /api/v1/approvals placed before /{approval_id} | FastAPI path matching: parameterized route would match "?status=pending" as approval_id |
| notify_teams() generic dispatcher | Single function for all card types reduces duplication; bot renders cards |
| Cross-partition query for pending approvals | Acceptable for small pending counts; used by scheduler, not hot path |
