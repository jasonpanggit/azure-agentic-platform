# Plan 05-02 — SSE Streaming + Chat Panel Components

**Status:** COMPLETE
**Date:** 2026-03-27
**Branch:** phase-5-wave-0-test-infrastructure

---

## What Was Built

### Task 5-02-01 — POST /api/v1/chat (API Gateway)

- **`services/api-gateway/models.py`**: Added `ChatRequest` (message + optional incident_id) and `ChatResponse` (thread_id + status) Pydantic models (D-06).
- **`services/api-gateway/chat.py`**: `create_chat_thread()` — creates a Foundry thread, posts the operator message as an AGENT-002 envelope, dispatches to the Orchestrator agent via `create_run()`.
- **`services/api-gateway/main.py`**: `POST /api/v1/chat` route — 202 Accepted, Entra Bearer auth required, 503 on misconfiguration.

### Task 5-02-02 — SSE Ring Buffer

- **`services/web-ui/lib/sse-buffer.ts`**: `SSEEventBuffer` class — `Map<string, BufferedEvent[]>` keyed by thread_id; FIFO eviction at 1000 events; `getEventsSince(seq)` filters by seq > N and TTL < 30min; `clear()` for thread completion. `globalEventBuffer` singleton exported for route handler.

### Task 5-02-03 — SSE Type Definitions

- **`services/web-ui/types/sse.ts`**: Full type hierarchy — `BaseSSEEvent`, `TokenEvent`, `TraceEvent`, `ApprovalGateTracePayload` (HITL gate with risk_level/target_resources/expires_at), `DoneEvent`, `ErrorEvent`, `SSEEventData` union, `Message` for ChatPanel state.

### Task 5-02-04 — SSE Route Handler

- **`services/web-ui/app/api/stream/route.ts`**: `GET /api/stream?thread_id=...&type=token|trace` — Node.js runtime, `force-dynamic`; replays missed events from `globalEventBuffer` when `Last-Event-ID` header present; 20-second SSE comment heartbeat (UI-008); proper SSE headers (`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`); abort-aware cleanup.

### Task 5-02-05 — React SSE Hook

- **`services/web-ui/lib/use-sse.ts`**: `useSSE()` hook — `EventSource` wrapper with monotonic sequence validation (ignores out-of-order/duplicate events); `done` event closes connection; browser-native auto-reconnect carries `Last-Event-ID`; returns `{ connected, reconnecting, lastSeq }`.

### Task 5-02-06 — Chat Panel Components + Full ChatPanel

- **`ChatBubble.tsx`**: Agent response bubble — react-markdown rendering, blinking streaming cursor (CSS animation), semibold agent name header.
- **`UserBubble.tsx`**: Right-aligned operator bubble — `colorBrandBackground` / `colorNeutralForegroundOnBrand`.
- **`ThinkingIndicator.tsx`**: Fluent UI `Spinner` (tiny) + "{agent} Agent is analyzing..." — shown while waiting for first token.
- **`ChatInput.tsx`**: `Textarea` + primary Send button with `SendRegular` icon; Enter submits, Shift+Enter newlines; disables during streaming.
- **`ProposalCard.tsx`**: Stub implementation (replaced by Plan 05-04 Task 5-04-08) — defines props interface, renders approve/reject buttons with orange border warning.
- **`ChatPanel.tsx`**: Full implementation — dual `useSSE` connections (token + trace streams); token delta accumulation into streaming messages (immutable state updates); `approval_gate` trace events attach `ProposalCard` inline; auto-scroll via `messagesEndRef`; empty state; error recovery; `POST /api/proxy/chat` submit; approval POST to `/api/proxy/approvals/{id}/approve|reject`.

### Task 5-02-07 — TraceTree Component

- **`TraceTree.tsx`**: Collapsed-by-default expandable panel (click or Enter) — shows event count summary; expands to Fluent UI `Tree` with `TreeItem` nodes; type icons (`WrenchRegular`/`ArrowForwardRegular`/`ShieldCheckmarkRegular`); status `Badge` (success=green/error=danger/pending=warning); click node to toggle monospace JSON payload; `maxHeight: 200px` with scroll.

---

## Commits

| Hash | Message |
|------|---------|
| fa7bcb5 | feat: add POST /api/v1/chat endpoint with Foundry thread creation |
| b314db6 | feat: add SSE ring buffer with 1000-event capacity and 30-min TTL |
| da3bca8 | feat: add SSE type definitions including ApprovalGateTracePayload |
| 9d9ed09 | feat: add SSE route handler with 20s heartbeat and Last-Event-ID reconnect replay |
| 93bc51f | feat: add chat panel components (ChatBubble, UserBubble, ThinkingIndicator, ChatInput) and full ChatPanel with SSE integration |
| 09d2d04 | feat: add TraceTree component with expandable JSON trace events panel |

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| globalEventBuffer singleton in route handler | Avoids per-request buffer instantiation; ring buffer is process-scoped and appropriate for single-instance Container App |
| Browser-native EventSource auto-reconnect | EventSource spec mandates Last-Event-ID replay header on reconnect; no manual retry logic needed |
| Monotonic seq validation in useSSE | Prevents out-of-order events from corrupting streaming message state |
| ProposalCard stub over compile error | ChatPanel imports ProposalCard; stub satisfies TypeScript compiler and defines the final props interface so 05-04 can drop in a full implementation without changing ChatPanel |
| Immutable message state updates | All `setMessages` calls use spread/slice patterns — never mutate existing message objects |
| Dual SSE connections (token + trace) | Token stream drives text accumulation; trace stream drives tool call visibility and approval gates — separating concerns allows independent reconnect |

---

## Files Created / Modified

### New Files
- `services/api-gateway/chat.py`
- `services/web-ui/lib/sse-buffer.ts`
- `services/web-ui/lib/use-sse.ts`
- `services/web-ui/types/sse.ts`
- `services/web-ui/app/api/stream/route.ts`
- `services/web-ui/components/ChatBubble.tsx`
- `services/web-ui/components/UserBubble.tsx`
- `services/web-ui/components/ThinkingIndicator.tsx`
- `services/web-ui/components/ChatInput.tsx`
- `services/web-ui/components/ProposalCard.tsx` (stub)
- `services/web-ui/components/TraceTree.tsx`

### Modified Files
- `services/api-gateway/models.py` — added ChatRequest, ChatResponse
- `services/api-gateway/main.py` — added imports, /api/v1/chat route
- `services/web-ui/components/ChatPanel.tsx` — replaced shell with full implementation

---

## Dependencies

`react-markdown` is already in `package.json` (added in 05-00). No new npm installs required for this plan.

---

## What 05-04 Will Replace

- `services/web-ui/components/ProposalCard.tsx` — stub replaced with full HITL approval card (risk badge, countdown timer, confirmation modal).
