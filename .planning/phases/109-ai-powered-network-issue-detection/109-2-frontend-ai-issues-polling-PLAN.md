---
wave: 2
phase: 109
title: Frontend — AI Issues Polling, Source Badge, and Merged Issues List
depends_on: "Wave 1 (GET /api/v1/network-topology/ai-issues backend endpoint)"
files_modified:
  - services/web-ui/app/api/proxy/network/topology/ai-issues/route.ts (NEW)
  - services/web-ui/components/NetworkTopologyTab.tsx (extend NetworkIssue type, add polling, AI badge)
autonomous: true
---

# Wave 2 — Frontend: AI Issues Polling, Source Badge, Merged Issues List

## Goal

After the topology loads, the frontend polls `GET /api/proxy/network/topology/ai-issues` every 3s
(max 5 attempts = 15s total). When AI issues arrive (`status: "ready"`), they are appended to the
issues list — no deduplication needed since AI issue IDs are prefixed `ai-`. Each AI issue card
shows a small `🤖 AI` source badge. The issues count pill in the toolbar updates to reflect the
total. A subtle "AI analysis in progress…" indicator appears while polling.

---

## Task 1 — Create proxy route `app/api/proxy/network/topology/ai-issues/route.ts`

<read_first>
- services/web-ui/app/api/proxy/network/topology/route.ts (copy pattern exactly)
- services/web-ui/lib/api-gateway.ts (getApiGatewayUrl, buildUpstreamHeaders)
</read_first>

<action>
Create `services/web-ui/app/api/proxy/network/topology/ai-issues/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/topology/ai-issues' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = request.nextUrl;
    const qs = searchParams.toString();

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/network-topology/ai-issues${qs ? `?${qs}` : ''}`,
      {
        method: 'GET',
        headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
        signal: AbortSignal.timeout(10000),
      }
    );

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.info('ai-issues fetched', { status: data?.status, count: data?.issues?.length ?? 0 });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
```
</action>

<acceptance_criteria>
- File exists at `services/web-ui/app/api/proxy/network/topology/ai-issues/route.ts`
- `grep -n "ai-issues" services/web-ui/app/api/proxy/network/topology/ai-issues/route.ts` → upstream URL contains `ai-issues`
- `grep -n "AbortSignal.timeout(10000)" services/web-ui/app/api/proxy/network/topology/ai-issues/route.ts` → timeout set
- `grep -n "force-dynamic" services/web-ui/app/api/proxy/network/topology/ai-issues/route.ts` → dynamic export present
</acceptance_criteria>

---

## Task 2 — Extend `NetworkIssue` type and add AI polling state in `NetworkTopologyTab.tsx`

<read_first>
- services/web-ui/components/NetworkTopologyTab.tsx lines 74–99 (NetworkIssue interface, TopologyData interface)
- services/web-ui/components/NetworkTopologyTab.tsx lines 1395–1440 (existing state declarations near issues/chat state)
- services/web-ui/components/NetworkTopologyTab.tsx lines 1560–1640 (fetchTopology / data-loading region — locate where topology load completes)
</read_first>

<action>

**Step A — Extend `NetworkIssue` interface** (lines ~74–93):
Add `source?: 'rule' | 'ai'` as an optional field at the end of the `NetworkIssue` interface body, before the closing `}`.

```typescript
  source?: 'rule' | 'ai'
```

**Step B — Add AI polling state** near the existing `issuesOpen` state (around line 1405). Insert after `const [focusedIssueIndex, setFocusedIssueIndex] = useState<number | null>(null)`:

```typescript
  // AI analysis polling state (Phase 109)
  const [aiAnalysisPending, setAiAnalysisPending] = useState(false)
  const aiPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const aiPollAttemptsRef = useRef(0)
  const AI_POLL_MAX_ATTEMPTS = 5
  const AI_POLL_INTERVAL_MS = 3000
```

**Step C — Add `pollAiIssues` function** — define it near `focusIssue` and `handleRemediate` (around line 1620). Insert a new `useCallback` after the existing state declarations but before `handleRemediate`:

```typescript
  // Poll for AI analysis results — called after topology loads
  const pollAiIssues = useCallback((subIds: string[]) => {
    if (aiPollRef.current) clearInterval(aiPollRef.current)
    aiPollAttemptsRef.current = 0
    setAiAnalysisPending(true)

    aiPollRef.current = setInterval(async () => {
      aiPollAttemptsRef.current += 1
      try {
        // No subscription_id filter — backend resolves the same set as trigger_ai_analysis,
        // ensuring the cache key matches (passing only subIds[0] would produce a different key).
        const res = await fetch(`/api/proxy/network/topology/ai-issues`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()

        if (data.status === 'ready') {
          const aiIssues: NetworkIssue[] = (data.issues ?? [])
          setTopologyData((prev) => {
            if (!prev) return prev
            // Append AI issues, avoiding duplicates by id
            const existingIds = new Set(prev.issues.map((i) => i.id))
            const newAiIssues = aiIssues.filter((i) => !existingIds.has(i.id))
            return { ...prev, issues: [...prev.issues, ...newAiIssues] }
          })
          setAiAnalysisPending(false)
          if (aiPollRef.current) clearInterval(aiPollRef.current)
        } else if (data.status === 'error') {
          setAiAnalysisPending(false)
          if (aiPollRef.current) clearInterval(aiPollRef.current)
        } else if (aiPollAttemptsRef.current >= AI_POLL_MAX_ATTEMPTS) {
          setAiAnalysisPending(false)
          if (aiPollRef.current) clearInterval(aiPollRef.current)
        }
      } catch {
        if (aiPollAttemptsRef.current >= AI_POLL_MAX_ATTEMPTS) {
          setAiAnalysisPending(false)
          if (aiPollRef.current) clearInterval(aiPollRef.current)
        }
      }
    }, AI_POLL_INTERVAL_MS)
  }, [])
```

**Step D — Trigger polling after topology loads** — locate the function that sets topology data (search for `setTopologyData(` in the file). After the line that sets topology data from the API response, add:

```typescript
        // Phase 109: kick off AI analysis polling
        pollAiIssues(subscriptionIds)
```

Where `subscriptionIds` is whatever variable holds the current subscription ID array at that call site. If the call site has a single `subscription_id` string, pass `[subscription_id].filter(Boolean)`.

**Step E — Cleanup interval on unmount** — find the existing `useEffect` cleanup (the one with `return () => {...}` that cleans up Cytoscape, polling intervals, etc.). Add inside its cleanup function:

```typescript
      if (aiPollRef.current) clearInterval(aiPollRef.current)
```
</action>

<acceptance_criteria>
- `grep -n "source\?: 'rule' | 'ai'" services/web-ui/components/NetworkTopologyTab.tsx` → field present in NetworkIssue interface
- `grep -n "aiAnalysisPending" services/web-ui/components/NetworkTopologyTab.tsx` → state declared
- `grep -n "pollAiIssues" services/web-ui/components/NetworkTopologyTab.tsx` → function defined and called
- `grep -n "ai-issues" services/web-ui/components/NetworkTopologyTab.tsx` → proxy URL referenced in pollAiIssues
- `grep -n "AI_POLL_MAX_ATTEMPTS" services/web-ui/components/NetworkTopologyTab.tsx` → constant declared as 5
- `grep -n "clearInterval(aiPollRef" services/web-ui/components/NetworkTopologyTab.tsx` → at least 2 occurrences (stop on ready + cleanup)
</acceptance_criteria>

---

## Task 3 — AI source badge on issue cards and "AI analysis in progress" indicator

<read_first>
- services/web-ui/components/NetworkTopologyTab.tsx lines 2427–2560 (issues drawer SheetContent — the issue card rendering loop)
- services/web-ui/components/NetworkTopologyTab.tsx lines 2440–2445 (SheetTitle with issue count — where to add the pending indicator)
</read_first>

<action>

**Step A — "AI analysis in progress" indicator** — inside the issues drawer `SheetContent`, immediately after the `<SheetTitle>` element (around line 2443), add:

```tsx
          {aiAnalysisPending && (
            <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
              🤖 AI analysis in progress…
            </p>
          )}
```

**Step B — AI source badge on each issue card** — locate the block that renders individual issue cards (find the map over `filteredIssues` or equivalent). Inside the issue card, find where the `severity` badge is rendered. After the severity badge, add the AI source badge conditionally:

```tsx
                          {issue.source === 'ai' && (
                            <span
                              className="text-[9px] px-1.5 py-0.5 rounded font-semibold"
                              style={{
                                background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                                color: 'var(--accent-blue)',
                                border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
                              }}
                            >
                              🤖 AI
                            </span>
                          )}
```

The exact insertion point: find the severity pill/badge render. The AI badge should appear immediately after it, on the same line (flex row).
</action>

<acceptance_criteria>
- `grep -n "AI analysis in progress" services/web-ui/components/NetworkTopologyTab.tsx` → text present
- `grep -n "aiAnalysisPending &&" services/web-ui/components/NetworkTopologyTab.tsx` → conditional render present
- `grep -n "issue.source === 'ai'" services/web-ui/components/NetworkTopologyTab.tsx` → badge condition present
- `grep -n "🤖 AI" services/web-ui/components/NetworkTopologyTab.tsx` → badge text present
- `grep -n "accent-blue" services/web-ui/components/NetworkTopologyTab.tsx` → semantic token used (not hardcoded Tailwind color)
</acceptance_criteria>

---

## Verification

```bash
cd services/web-ui
npx tsc --noEmit 2>&1 | head -30
```

Expected: 0 TypeScript errors related to changed files. (Pre-existing unrelated errors from other files are acceptable.)

Manual smoke test checklist (for human reviewer):
- [ ] Topology tab loads instantly with rule-based issues
- [ ] "🤖 AI analysis in progress…" appears in issues drawer header after load
- [ ] After ≤15s, AI issues appear in the drawer with `🤖 AI` badge
- [ ] Issue count pill updates to include AI issues
- [ ] If subscription has no AI issues, indicator disappears quietly after polling exhausted

## Must-Haves

- [ ] Proxy route `app/api/proxy/network/topology/ai-issues/route.ts` exists
- [ ] `NetworkIssue` interface has `source?: 'rule' | 'ai'`
- [ ] `pollAiIssues()` polls every 3s, max 5 attempts, stops on `ready` or `error`
- [ ] AI issues merged into `topologyData.issues` without wiping rule-based issues (spread pattern)
- [ ] AI badge uses `var(--accent-blue)` semantic token — no hardcoded Tailwind color classes
- [ ] Interval cleaned up on component unmount
- [ ] No `console.log` statements introduced
