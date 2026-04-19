---
wave: 2
phase: 109
title: Frontend — AI Issues Polling, Source Badge, and Merged Issues List
status: complete
---

# Wave 2 Summary — Frontend: AI Issues Polling, Source Badge, Merged Issues List

## Changes Delivered

### Task 1 — Proxy route `app/api/proxy/network/topology/ai-issues/route.ts` (NEW)
- GET-only proxy following the topology route pattern exactly
- Uses `getApiGatewayUrl()` + `buildUpstreamHeaders()` from `@/lib/api-gateway`
- `AbortSignal.timeout(10000)` — intentionally 10s (fast cache read, shorter than default 15s)
- Forwards query params via `searchParams.toString()`
- Returns 502 on unreachable gateway

### Task 2 — `NetworkTopologyTab.tsx` — Type extension + polling
- **Step A**: Added `source?: 'rule' | 'ai'` to `NetworkIssue` interface
- **Step B**: Added AI polling state (`aiAnalysisPending`, `aiPollRef`, `aiPollAttemptsRef`, `AI_POLL_MAX_ATTEMPTS = 5`, `AI_POLL_INTERVAL_MS = 3000`)
- **Step C**: Added `pollAiIssues` useCallback — polls every 3s, max 5 attempts (15s total), stops on `ready` or `error` status; AI issues merged into `topologyData.issues` without overwriting rule-based issues
- **Step D**: `pollAiIssues()` called immediately after `setTopologyData(data)` in `fetchData`
- **Step E**: Interval cleaned up in unmount useEffect alongside animation frame cleanup

### Task 3 — AI UI chrome in issues drawer
- "🤖 AI analysis in progress…" text appears below `<SheetTitle>` while `aiAnalysisPending` is true
- `🤖 AI` source badge rendered after `SeverityBadge` in `IssueCard` when `issue.source === 'ai'`
- Badge uses `var(--accent-blue)` semantic CSS token — no hardcoded Tailwind colors

## Verification
- `npx tsc --noEmit` → 0 errors in production files
- No `console.log` statements introduced
- Immutable update pattern used for merging AI issues (`spread` into new array)
