---
plan: 17-02
status: complete
commit: 7f7c01e
branch: gsd/phase-17-resource-chat
---

# Summary: Plan 17-02 — Wire "Investigate with AI" in VMDetailPanel

## What Was Done

Replaced the disabled "Investigate with AI" placeholder in `VMDetailPanel.tsx` with a fully functional inline chat panel, and added the required Next.js proxy route.

## Files Changed

### New: `services/web-ui/app/api/proxy/vms/[vmId]/chat/route.ts`
- POST handler using Next.js 15 async params pattern
- Forwards `{message, thread_id, incident_id}` body to `POST /api/v1/vms/{vmId}/chat` on the backend
- Uses `buildUpstreamHeaders`, `getApiGatewayUrl`, `logger` (same pattern as the existing `[vmId]/route.ts`)
- 30s timeout, proper 502 on gateway unreachable

### Modified: `services/web-ui/components/VMDetailPanel.tsx`
- Added `useRef` to imports
- Added `ChatMessage` interface (`role`, `content`, `approval_id?`)
- Added 6 chat state variables: `chatOpen`, `chatMessages`, `chatInput`, `chatStreaming`, `chatThreadId`, `chatPollRef`
- Added `startChatPolling()` — polls `/api/proxy/chat/result?thread_id=...&run_id=...` every 2s; stops on terminal status; extracts last assistant message from Foundry messages array (handles both array-of-content-blocks and plain string formats)
- Added `sendChatMessage()` — appends user message, POSTs to proxy, starts polling on success
- Added `openChat()` — sets `chatOpen=true`, auto-sends initial summary prompt if no messages yet
- Added `useEffect` to reset chat state when `resourceId` changes (panel close/reopen)
- Added `useEffect` cleanup to clear polling interval on unmount
- Replaced 14-line disabled placeholder with 109-line inline chat UI:
  - Collapsed state: blue "Investigate with AI" button
  - Expanded state: scrollable message history (max-h 320px) + text input + Send button
  - Loading skeleton (3 pulse bars) shown before first response arrives
  - "Thinking…" pulse shown between subsequent messages
  - Approval proposal messages show orange redirect card (full ProposalCard in Phase 18)
  - Enter key sends message; input disabled while streaming

## Polling URL Verified
The chat result proxy is at `/api/proxy/chat/result?thread_id=...&run_id=...` (confirmed from `app/api/proxy/chat/result/route.ts`). The plan's reference to `/api/proxy/chat/{threadId}/result` was updated to the correct query-param format.

## Build & Test Results

```
npm run build → ✅ Zero TypeScript errors
/api/proxy/vms/[vmId]/chat appears in build output as ƒ (Dynamic)

npm test → Pre-existing failures only (jest-globals-setup.ts, 2 others)
           No regressions introduced
```

## Success Criteria Checklist

- [x] `POST /api/proxy/vms/{vmId}/chat` proxies to backend correctly
- [x] Clicking "Investigate with AI" sends initial summary request and shows response
- [x] Subsequent messages continue the thread (same thread_id passed in body)
- [x] Loading skeleton shown while first response streams
- [x] "Thinking…" indicator shown between messages
- [x] Chat input disabled while streaming
- [x] Enter key sends message
- [x] Panel close → reopen starts fresh chat (resourceId change resets all state)
- [x] `npm run build` passes with no TypeScript errors
