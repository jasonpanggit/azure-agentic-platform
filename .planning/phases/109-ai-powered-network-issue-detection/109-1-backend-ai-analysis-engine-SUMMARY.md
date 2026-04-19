# Wave 1 Summary — Backend: Async AI Analysis Engine + ai-issues Endpoint

**Phase:** 109  
**Wave:** 1  
**Status:** ✅ Complete  
**Tests:** 10/10 passing

## Files Changed

| File | Change |
|------|--------|
| `services/api-gateway/network_topology_service.py` | Added `source: Optional[str]` field to `NetworkIssue` TypedDict |
| `services/api-gateway/network_topology_ai.py` | **NEW** — async AI analysis engine |
| `services/api-gateway/network_topology_endpoints.py` | Added `trigger_ai_analysis` call + `GET /api/v1/network-topology/ai-issues` endpoint |
| `services/api-gateway/tests/test_network_topology_ai.py` | **NEW** — 10 unit tests |

## What Was Built

### `network_topology_ai.py`
- **In-memory cache** with 5-minute TTL (`_AI_TTL_SECONDS = 300`), keyed by sorted subscription ID MD5 hash
- **`trigger_ai_analysis()`** — fire-and-forget daemon thread; marks cache as `pending` immediately, runs `_run_analysis` in background
- **`get_ai_issues()`** — cache reader returning `{"status": "pending"|"ready"|"error", "issues": [...], "error": ...}`
- **`_analyze_topology()`** — calls `gpt-4.1` via `_get_openai_client()` (local import to avoid circular)
- **`_build_prompt()`** — chunks top 20 nodes by complexity score, summarises top 30 existing issues
- **`_parse_and_validate()`** — strips code fences, parses JSON array, validates severity, deduplicates, prefixes IDs with `ai-`, sets `source="ai"`
- **`_SYSTEM_PROMPT`** — CIS Azure Benchmark 2.0-aligned prompt for novel issue detection

### Endpoint
- `GET /api/v1/network-topology/ai-issues` — polls cache, returns status + issues array
- `trigger_ai_analysis()` called inside `get_topology()` after topology fetch (non-blocking)

## Acceptance Criteria Met

- [x] `trigger_ai_analysis`, `get_ai_issues`, `_parse_and_validate` all defined
- [x] `source="ai"` on every AI-generated issue
- [x] IDs prefixed `ai-`
- [x] `GET /api/v1/network-topology/ai-issues` route registered
- [x] `trigger_ai_analysis` called from `get_topology()` (fire-and-forget)
- [x] 5-min TTL cache (`_AI_TTL_SECONDS = 300`)
- [x] No module-level import of `_get_openai_client` (local import inside function)
- [x] 10 unit tests, all passing
