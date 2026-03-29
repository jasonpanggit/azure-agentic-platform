# Debug: Subsequent Messages No Response

**Issue:** After the first successful message in a chat thread, subsequent messages get no response at all.

**Status:** FIXED

## Symptoms

1. First message "Show my virtual machines" gets a response
2. Second message "List VMs with high CPU usage" shows as sent bubble but no response
3. Third message "Which VMs are stopped?" — same silence
4. No error visible in UI, no error bubble

## Root Causes Found

### Bug 1 (Backend): `get_chat_result()` returns the WRONG run

**File:** `services/api-gateway/chat.py:131-136`

```python
runs = client.runs.list(thread_id=thread_id)
run_list = list(runs)
latest_run = run_list[0]  # BUG: [0] is the OLDEST run, not the newest
```

The Foundry `runs.list()` API returns runs in **chronological order** (oldest first). When message #2 creates run #2 on the same thread, the poller still picks up run #1 (already `completed`), reads its old reply, and returns it immediately.

The SSE stream route sees "completed" on the first poll, emits the stale reply (seq=1), and closes. But the client's dedup guard drops it because `seq(1) <= lastSeqRef(2)`.

**Fix:** Sort `run_list` by `created_at` descending, or take `run_list[-1]` to get the most recent run.

### Bug 2 (Frontend): `lastSeqRef` never resets between runs — dedup kills new events

**File:** `services/web-ui/lib/use-sse.ts:38, 46-47`

```typescript
const lastSeqRef = useRef(0);
// ...
// Do NOT reset lastSeqRef — preserve last seq...  // BUG
```

The server starts `seq` at 0 for each new SSE connection (`route.ts:39`). But the client retains `lastSeqRef` from the previous run (e.g., `2` after first run's token+done). All new events (`seq=1,2`) are dropped by `if (seq > lastSeqRef.current)`.

Even if Bug 1 were fixed, Bug 2 would still cause silence.

**Fix:** Reset `lastSeqRef.current = 0` when opening a new connection for a new `runKey`.

### Bug Chain

```
Message #2 sent
  -> POST /api/v1/chat (creates run_2 on existing thread)
  -> ChatPanel bumps runKey (1 -> 2)
  -> useSSE reopens SSE connection
  -> Server starts polling get_chat_result()
  -> [Bug 1] get_chat_result() returns run_1 (old, completed) instead of run_2
  -> Server emits stale reply with seq=1, then done with seq=2
  -> [Bug 2] Client lastSeqRef=2, drops seq=1 and seq=2 (not > 2)
  -> SILENCE
```

## Fixes Applied

1. **chat.py:** Take the last element of `run_list` (most recent run) instead of `[0]`
2. **use-sse.ts:** Reset `lastSeqRef.current = 0` at the start of `connect()` when `runKey` changes
3. **chat.py:** Also accept `run_id` parameter in `get_chat_result()` for targeted polling (defense in depth)
4. **stream route.ts:** Pass `run_id` from SSE query params to the result proxy (future-proofing)

## Verification

- [x] First message gets response (unchanged, no regression)
- [x] Second message on same thread gets response (Bug 1 + Bug 2 fixed)
- [x] Third message on same thread gets response (same fix chain)
- [x] No duplicate/stale replies (run_id targeting prevents old run pickup)
- [x] SSE reconnect still works (dedup effective within a single run — lastSeqRef only resets on new connection, not mid-stream)
- [x] All 18 existing tests pass (1 pre-existing failure unrelated to this fix)
- [x] 5 new tests added for get_chat_result run selection and run_id targeting

## Files Changed

| File | Change |
|------|--------|
| `services/api-gateway/chat.py` | `run_list[-1]` instead of `[0]`; added `run_id` param to `get_chat_result()` with `runs.retrieve()` shortcut |
| `services/api-gateway/main.py` | Added optional `run_id` query param to GET endpoint; return `run_id` in chat response |
| `services/api-gateway/models.py` | Added `run_id` field to `ChatResponse` |
| `services/web-ui/lib/use-sse.ts` | Reset `lastSeqRef.current = 0` on new connection; accept and forward `runId` |
| `services/web-ui/app/api/stream/route.ts` | Extract `run_id` from query params, forward to polling URL |
| `services/web-ui/app/api/proxy/chat/result/route.ts` | Forward `run_id` query param to API gateway |
| `services/web-ui/components/ChatPanel.tsx` | Track `runId` state, pass to `useSSE` hook |
| `services/api-gateway/tests/test_chat_endpoint.py` | 5 new tests for run selection and `run_id` targeting |
