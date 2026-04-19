---
status: all_fixed
findings_in_scope: 8
fixed: 8
skipped: 4
iteration: 1
---

# Review Fix Report — Phase 108: Network Topology Full Issue Detection

**Applied:** 2026-04-19  
**Commit:** `fix(108): CR-002 exact match in _resolve_resource_nsg, CR-003 explicit TTL tuple, ...`

---

## Findings Fixed

| ID | Severity | Description | Fix Applied |
|----|----------|-------------|-------------|
| CR-007 | critical | PE approve: no subscription ownership check + risky fallback guesses connection name | Added subscription ID cross-check before ARM call; removed guessed `{pe_name}-connection` fallback; returns error when no connections found |
| CR-001 | warning | `_CONVERSATION_HISTORY` dict unbounded key growth | Added 500-key LRU eviction loop after writing to `_CONVERSATION_HISTORY` in `_stream_network_chat` |
| CR-002 | warning | `_resolve_resource_nsg` uses `in` (substring) instead of `==` (exact match) | Changed to `resource_id_lower == node["id"].lower()` |
| CR-003 | warning | Cache TTL manipulation via timestamp backdating — fragile, non-obvious | Refactored to store `(insert_time, effective_ttl, value)` 3-tuple; expiry check is `monotonic() - insert_time < effective_ttl`; also fixed the single other unpack site in `evaluate_path_check` |
| CR-004 | warning | `_detect_asymmetries` O(N²×M) with no cap on NSG count | Added `_NSG_ASYMMETRY_CAP = 50` with truncation + warning log when exceeded |
| CR-009 | warning | `RemediateRequest.issue_id` accepts arbitrary strings | Added `Field(min_length=16, max_length=16, pattern=r'^[0-9a-f]{16}$')` constraint; updated test fixtures to use valid 16-char hex IDs |
| CR-010 | warning | System prompt embeds user-controlled `selected_node_id`/`subscription_ids` without sanitisation | Added `_sanitise_context()` helper that strips newlines, angle brackets, and truncates to 200 chars before embedding in the context block |
| CR-012 | warning | `protocol` field on `PathCheckRequest` is free-form string | Changed to `Literal["TCP", "UDP", "ICMP", "*"]`; added `Literal` to typing imports |

## Findings Skipped (Info severity — out of scope)

| ID | Severity | Reason |
|----|----------|--------|
| CR-005 | info | NSG shadowing heuristic limitation — documentation improvement only |
| CR-006 | info | Internal maps cached in memory — acceptable trade-off, deferred |
| CR-008 | info | WAL swallows Cosmos errors — fire-and-forget is intentional per platform conventions |
| CR-011 | info | Non-null assertion `step.cli!` in TSX — fixed as a low-effort improvement (`?? ''`) |

> Note: CR-011 was listed as Info in scope-skip list but was a trivial 1-line fix; applied anyway.

## Test Results

```
102 passed, 2 warnings in 0.28s
```

All pre-existing tests pass. No regressions introduced.
