---
status: complete
completed: "2026-04-16"
---

## What Was Built

Push notification backend for on-call operators — VAPID-signed Web Push delivery for P0/P1 incidents.

## Files Created/Modified

| File | Action |
|------|--------|
| `services/api-gateway/push_notifications.py` | Created — 183 lines. VAPID push service with Cosmos subscription store, 3 REST routes, `send_push_to_all` dispatcher |
| `services/api-gateway/requirements.txt` | Already had `pywebpush>=2.0.0` from plan prep |
| `services/api-gateway/main.py` | Modified — import push_router + send_push_to_all, register router, fire-and-forget dispatch in `ingest_incident` |
| `services/api-gateway/tests/test_push_notifications.py` | Created — 15 tests, all passing |

## Key Decisions

- **Partition key**: `subscription_endpoint_hash` (SHA-256[:32] of endpoint URL) — deterministic, no PII stored as key
- **SDK guard**: `webpush = None` on `ImportError` — module loads without pywebpush installed
- **Fire-and-forget**: `asyncio.ensure_future(send_push_to_all(...))` — never blocks incident ingestion response
- **410 auto-cleanup**: Expired subscriptions removed from Cosmos on 410 HTTP response from push service
- **Severity filter**: Only `Sev0`, `P0`, `Sev1`, `P1` trigger push — lower severities skip

## Test Results

```
15 passed in 0.04s
```
