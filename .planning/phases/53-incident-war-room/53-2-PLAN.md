---
wave: 2
depends_on: [53-1-PLAN.md]
files_modified:
  - services/web-ui/components/WarRoomPanel.tsx
  - services/web-ui/components/AvatarGroup.tsx
  - services/web-ui/components/AnnotationLayer.tsx
  - services/web-ui/components/AlertFeed.tsx
  - services/web-ui/app/api/proxy/war-room/join/route.ts
  - services/web-ui/app/api/proxy/war-room/annotations/route.ts
  - services/web-ui/app/api/proxy/war-room/stream/route.ts
  - services/web-ui/app/api/proxy/war-room/heartbeat/route.ts
  - services/web-ui/app/api/proxy/war-room/handoff/route.ts
autonomous: true
---

# Plan 53-2: War Room Frontend — WarRoomPanel, AvatarGroup, AnnotationLayer, Proxy Routes

## Goal

Build the complete war room UI: `WarRoomPanel.tsx` (side-sheet that opens from any incident row in AlertFeed), `AvatarGroup.tsx` (presence indicator showing operators with open incident tabs, 30s heartbeat), `AnnotationLayer.tsx` (annotation input + pinned annotation list), 5 proxy routes, and an "Open War Room" button wired into `AlertFeed.tsx`. All CSS uses `var(--accent-*)` semantic tokens — zero hardcoded Tailwind color values. SSE stream connects to the backend `/war-room/stream` endpoint for real-time annotation push.

## Context

The war room UI follows the existing slide-over pattern: `PatchDetailPanel.tsx` and `VMDetailPanel.tsx` use a right-side sheet with a close button — same approach. `AnnotationLayer.tsx` is a standalone component that accepts a `traceEventId` prop so it can be embedded inside `TraceTree.tsx` in a future phase (out of scope here — only inline use in `WarRoomPanel`). The SSE stream is consumed via `fetch` with `ReadableStream` body parsing (same pattern as `app/api/stream/route.ts` — NOT a new `EventSource` — because the stream goes through a Next.js proxy route that adds the auth header). The presence heartbeat is a `setInterval` in `WarRoomPanel` that fires every 30 seconds and calls `POST /api/proxy/war-room/heartbeat`.

<threat_model>
## Security Threat Assessment

**1. SSE proxy stream route**: The `/api/proxy/war-room/stream` route uses `fetch()` to the upstream then returns a `ReadableStream` passthrough. The Authorization header is forwarded via `buildUpstreamHeaders()`. No SSE data is modified — it is piped verbatim. No injection vector.

**2. Annotation content in UI**: `AnnotationLayer.tsx` renders annotation `content` using `<p className="...">` with React's default text-content rendering — not `dangerouslySetInnerHTML`. No XSS risk.

**3. `operator_id` display**: The component receives `display_name` from the war room doc (set by the backend from the JWT `name` claim). Displayed as plain text — no HTML injection.

**4. 30s heartbeat interval**: `setInterval` is cleared in the component `useEffect` cleanup function to prevent memory leaks and spurious calls after unmount.

**5. SSE stream cleanup**: The `AbortController` is called in the `useEffect` cleanup to abort the upstream fetch and prevent dangling async tasks when the panel closes.

**6. CSS semantic tokens**: All badge/avatar background colors use `color-mix(in srgb, var(--accent-*) 15%, transparent)` pattern — same as existing dark-mode-safe badges. No hardcoded hex or Tailwind color classes.
</threat_model>

---

## Tasks

### Task 1: Create 5 proxy routes for war room

<read_first>
- `services/web-ui/app/api/proxy/finops/cost-breakdown/route.ts` — FULL FILE — exact proxy pattern: `getApiGatewayUrl`, `buildUpstreamHeaders`, `AbortSignal.timeout(15000)`, error handling with `NextResponse.json`
- `services/web-ui/app/api/stream/route.ts` lines 1–100 — `ReadableStream` + pipe pattern for the SSE stream proxy (different from plain JSON proxy routes — needs passthrough not `res.json()`)
</read_first>

<action>
Create 5 proxy route files. Files 1–2 and 4–5 follow the standard JSON proxy pattern (same as `finops/cost-breakdown/route.ts`). File 3 (stream) uses a `ReadableStream` passthrough pattern.

**File 1: `services/web-ui/app/api/proxy/war-room/join/route.ts`**
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/war-room/join' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/war-room/join?incident_id=<id>
 * Body: { display_name?, role? }
 *
 * Proxies to POST /api/v1/incidents/{id}/war-room
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const incidentId = searchParams.get('incident_id');
    if (!incidentId) {
      return NextResponse.json({ error: 'incident_id is required' }, { status: 400 });
    }
    const body = await request.text();
    log.info('proxy request', { method: 'POST', incident_id: incidentId });
    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room`,
      {
        method: 'POST',
        headers: { ...upstreamHeaders, 'Content-Type': 'application/json' },
        body: body || '{}',
        signal: AbortSignal.timeout(15000),
      }
    );
    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}` }, { status: res.status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
```

**File 2: `services/web-ui/app/api/proxy/war-room/annotations/route.ts`**
- Method: `POST`
- Log child: `{ route: '/api/proxy/war-room/annotations' }`
- Upstream: `POST ${apiGatewayUrl}/api/v1/incidents/${incidentId}/war-room/annotations`
- Reads `incident_id` from `searchParams`
- Error fallback: `{ error: message }`
- Same structure as File 1 (POST with body passthrough)

**File 3: `services/web-ui/app/api/proxy/war-room/stream/route.ts`** (SSE passthrough):
```typescript
import { NextRequest } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/war-room/stream' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/war-room/stream?incident_id=<id>
 *
 * Pipes the upstream SSE stream from the API gateway to the browser.
 * Adds Authorization header (not possible from browser EventSource).
 */
export async function GET(request: NextRequest): Promise<Response> {
  const { searchParams } = new URL(request.url);
  const incidentId = searchParams.get('incident_id');
  if (!incidentId) {
    return new Response('incident_id is required', { status: 400 });
  }

  const apiGatewayUrl = getApiGatewayUrl();
  const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);
  log.info('sse stream connect', { incident_id: incidentId });

  const upstream = await fetch(
    `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room/stream`,
    {
      headers: upstreamHeaders,
      // No AbortSignal.timeout here — SSE streams are long-lived by design
    }
  );

  if (!upstream.ok || !upstream.body) {
    log.error('upstream sse error', { status: upstream.status });
    return new Response('Failed to connect to war room stream', { status: upstream.status });
  }

  // Pipe the upstream SSE body verbatim to the browser
  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    },
  });
}
```

**File 4: `services/web-ui/app/api/proxy/war-room/heartbeat/route.ts`**
- Method: `POST`, no body
- Log child: `{ route: '/api/proxy/war-room/heartbeat' }`
- Upstream: `POST ${apiGatewayUrl}/api/v1/incidents/${incidentId}/war-room/heartbeat`
- Reads `incident_id` from `searchParams`
- Error fallback: `{ error: message }`
- `AbortSignal.timeout(5000)` (heartbeat should be fast)

**File 5: `services/web-ui/app/api/proxy/war-room/handoff/route.ts`**
- Method: `POST`, no body
- Log child: `{ route: '/api/proxy/war-room/handoff' }`
- Upstream: `POST ${apiGatewayUrl}/api/v1/incidents/${incidentId}/war-room/handoff`
- `AbortSignal.timeout(45000)` (GPT-4o can take up to 30s — use a longer timeout)
- Error fallback: `{ error: message, summary: null }`
</action>

<acceptance_criteria>
- `services/web-ui/app/api/proxy/war-room/join/route.ts` exists with `grep "POST.*war-room" services/web-ui/app/api/proxy/war-room/join/route.ts` exits 0
- `services/web-ui/app/api/proxy/war-room/annotations/route.ts` exists
- `services/web-ui/app/api/proxy/war-room/stream/route.ts` exists with `grep "text/event-stream" services/web-ui/app/api/proxy/war-room/stream/route.ts` exits 0
- `services/web-ui/app/api/proxy/war-room/heartbeat/route.ts` exists with `grep "AbortSignal.timeout(5000)" services/web-ui/app/api/proxy/war-room/heartbeat/route.ts` exits 0
- `services/web-ui/app/api/proxy/war-room/handoff/route.ts` exists with `grep "AbortSignal.timeout(45000)" services/web-ui/app/api/proxy/war-room/handoff/route.ts` exits 0
- `grep "buildUpstreamHeaders" services/web-ui/app/api/proxy/war-room/join/route.ts` exits 0
- `grep "getApiGatewayUrl" services/web-ui/app/api/proxy/war-room/stream/route.ts` exits 0
</acceptance_criteria>

---

### Task 2: Create `services/web-ui/components/AvatarGroup.tsx`

<read_first>
- `services/web-ui/components/VMDetailPanel.tsx` lines 1–40 — import pattern for shadcn/ui components, lucide icons, `cn()` utility import from `@/lib/utils`
- `services/web-ui/components/DashboardPanel.tsx` lines 24–50 — CSS semantic token usage: `var(--accent-blue)`, `var(--text-primary)`, `var(--bg-canvas)`, `color-mix(in srgb, var(--accent-*) 15%, transparent)` badge pattern
</read_first>

<action>
Create `services/web-ui/components/AvatarGroup.tsx`:

```typescript
'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

export interface WarRoomParticipant {
  operator_id: string;
  display_name: string;
  role: 'lead' | 'support';
  joined_at: string;
  last_seen_at: string;
}

interface AvatarGroupProps {
  participants: WarRoomParticipant[];
  /** Threshold in seconds; participants with last_seen_at older than this are shown as offline. Default: 60 */
  onlineThresholdSeconds?: number;
  className?: string;
}

/**
 * AvatarGroup — shows initials badges for war room participants.
 *
 * Online = last_seen_at within onlineThresholdSeconds (default 60s).
 * Lead operator gets a gold ring; support operators get the standard ring.
 * Dark-mode-safe: uses CSS semantic tokens only.
 */
export function AvatarGroup({
  participants,
  onlineThresholdSeconds = 60,
  className,
}: AvatarGroupProps) {
  const now = Date.now();

  function isOnline(p: WarRoomParticipant): boolean {
    const lastSeen = new Date(p.last_seen_at).getTime();
    return (now - lastSeen) / 1000 < onlineThresholdSeconds;
  }

  function getInitials(p: WarRoomParticipant): string {
    const name = p.display_name || p.operator_id;
    return name
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .slice(0, 2)
      .join('');
  }

  if (participants.length === 0) {
    return (
      <span className={cn('text-xs', className)} style={{ color: 'var(--text-secondary)' }}>
        No participants
      </span>
    );
  }

  return (
    <TooltipProvider>
      <div className={cn('flex -space-x-2', className)}>
        {participants.map((p) => {
          const online = isOnline(p);
          const isLead = p.role === 'lead';
          return (
            <Tooltip key={p.operator_id}>
              <TooltipTrigger asChild>
                <div
                  className="relative w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold cursor-default select-none border-2"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-blue) 20%, var(--bg-canvas))',
                    color: 'var(--accent-blue)',
                    borderColor: isLead ? 'var(--accent-yellow, #f59e0b)' : 'var(--border)',
                    opacity: online ? 1 : 0.45,
                  }}
                  aria-label={`${p.display_name || p.operator_id} (${p.role}${online ? '' : ', offline'})`}
                >
                  {getInitials(p)}
                  {/* Online indicator dot */}
                  {online && (
                    <span
                      className="absolute bottom-0 right-0 w-2 h-2 rounded-full border border-white"
                      style={{ background: 'var(--accent-green, #22c55e)' }}
                    />
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p className="font-medium">{p.display_name || p.operator_id}</p>
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {p.role} · {online ? 'online' : 'offline'}
                </p>
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
```
</action>

<acceptance_criteria>
- File `services/web-ui/components/AvatarGroup.tsx` exists
- `grep "'use client'" services/web-ui/components/AvatarGroup.tsx` exits 0
- `grep "export interface WarRoomParticipant" services/web-ui/components/AvatarGroup.tsx` exits 0
- `grep "export function AvatarGroup" services/web-ui/components/AvatarGroup.tsx` exits 0
- `grep "onlineThresholdSeconds" services/web-ui/components/AvatarGroup.tsx` exits 0
- `grep "var(--accent-blue)" services/web-ui/components/AvatarGroup.tsx` exits 0
- `grep "color-mix" services/web-ui/components/AvatarGroup.tsx` exits 0
- No hardcoded Tailwind color classes: `grep -E "bg-(red|green|blue|yellow|purple|gray)-[0-9]+" services/web-ui/components/AvatarGroup.tsx` exits 1 (no matches)
</acceptance_criteria>

---

### Task 3: Create `services/web-ui/components/AnnotationLayer.tsx`

<read_first>
- `services/web-ui/components/ChatInput.tsx` — FULL FILE — exact `Textarea` + `Button` pattern, `onKeyDown` submit on Enter, `disabled` prop handling
- `services/web-ui/components/ChatBubble.tsx` lines 1–40 — message bubble rendering pattern with prose classes and timestamps
- `services/web-ui/components/DashboardPanel.tsx` lines 100–140 — `var(--bg-surface)`, `var(--border)` token usage for card containers
</read_first>

<action>
Create `services/web-ui/components/AnnotationLayer.tsx`:

```typescript
'use client';

import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Pin, Send } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface Annotation {
  id: string;
  operator_id: string;
  display_name: string;
  content: string;
  trace_event_id: string | null;
  created_at: string;
}

interface AnnotationLayerProps {
  incidentId: string;
  annotations: Annotation[];
  /** If provided, new annotations will be pinned to this trace event */
  traceEventId?: string | null;
  onAnnotationAdded?: (annotation: Annotation) => void;
  className?: string;
}

/**
 * AnnotationLayer — annotation list + input for war room investigation notes.
 *
 * Calls POST /api/proxy/war-room/annotations to persist new annotations.
 * Renders existing annotations in chronological order.
 * Dark-mode safe — CSS semantic tokens only.
 */
export function AnnotationLayer({
  incidentId,
  annotations,
  traceEventId = null,
  onAnnotationAdded,
  className,
}: AnnotationLayerProps) {
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    const content = draft.trim();
    if (!content || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/proxy/war-room/annotations?incident_id=${encodeURIComponent(incidentId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content, trace_event_id: traceEventId ?? null }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `Error ${res.status}`);
      }
      const data = await res.json();
      setDraft('');
      onAnnotationAdded?.(data.annotation as Annotation);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save annotation');
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {/* Annotation list */}
      <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
        {annotations.length === 0 ? (
          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            No annotations yet. Pin a note to start the investigation record.
          </p>
        ) : (
          annotations.map((a) => (
            <div
              key={a.id}
              className="rounded-md px-3 py-2 text-sm"
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 8%, var(--bg-canvas))',
                borderLeft: '3px solid var(--accent-blue)',
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold text-xs" style={{ color: 'var(--text-primary)' }}>
                  {a.display_name || a.operator_id}
                </span>
                {a.trace_event_id && (
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1 py-0 flex items-center gap-1"
                    style={{ color: 'var(--accent-blue)', borderColor: 'var(--accent-blue)' }}
                  >
                    <Pin className="w-2.5 h-2.5" />
                    pinned
                  </Badge>
                )}
                <span className="ml-auto text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                  {new Date(a.created_at).toLocaleTimeString()}
                </span>
              </div>
              <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>
                {a.content}
              </p>
            </div>
          ))
        )}
      </div>

      {/* Input area */}
      <div className="flex flex-col gap-1">
        {traceEventId && (
          <p className="text-[10px] flex items-center gap-1" style={{ color: 'var(--accent-blue)' }}>
            <Pin className="w-3 h-3" />
            Note will be pinned to trace event
          </p>
        )}
        <div className="flex gap-2 items-end">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Add an investigation note… (Ctrl+Enter to save)"
            className="resize-none min-h-[60px] text-xs"
            disabled={submitting}
            maxLength={4096}
          />
          <Button
            size="sm"
            variant="default"
            onClick={handleSubmit}
            disabled={!draft.trim() || submitting}
            aria-label="Save annotation"
          >
            <Send className="w-3.5 h-3.5" />
          </Button>
        </div>
        {error && (
          <p className="text-xs" style={{ color: 'var(--accent-red)' }}>
            {error}
          </p>
        )}
        <p className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>
          {draft.length}/4096
        </p>
      </div>
    </div>
  );
}
```
</action>

<acceptance_criteria>
- File `services/web-ui/components/AnnotationLayer.tsx` exists
- `grep "'use client'" services/web-ui/components/AnnotationLayer.tsx` exits 0
- `grep "export interface Annotation" services/web-ui/components/AnnotationLayer.tsx` exits 0
- `grep "export function AnnotationLayer" services/web-ui/components/AnnotationLayer.tsx` exits 0
- `grep "trace_event_id" services/web-ui/components/AnnotationLayer.tsx` exits 0
- `grep "var(--accent-blue)" services/web-ui/components/AnnotationLayer.tsx` exits 0
- `grep "maxLength={4096}" services/web-ui/components/AnnotationLayer.tsx` exits 0
- `grep "Ctrl+Enter" services/web-ui/components/AnnotationLayer.tsx` exits 0
- No hardcoded Tailwind color classes: `grep -E "bg-(red|green|blue|yellow|purple)-[0-9]+" services/web-ui/components/AnnotationLayer.tsx` exits 1
</acceptance_criteria>

---

### Task 4: Create `services/web-ui/components/WarRoomPanel.tsx`

<read_first>
- `services/web-ui/components/PatchDetailPanel.tsx` lines 1–80 — full slide-over sheet pattern with close button, resizable handle, `Sheet`/`SheetContent` from shadcn/ui, or the CSS `fixed inset-y-0 right-0` panel approach
- `services/web-ui/components/AlertFeed.tsx` lines 1–50 — incident data shape `IncidentSummary` interface for TypeScript
- `services/web-ui/app/api/stream/route.ts` lines 78–160 — `ReadableStream` + decoder pattern for consuming SSE in the browser (`TextDecoder`, chunk iteration)
- `services/web-ui/components/AvatarGroup.tsx` (just written) — `WarRoomParticipant` interface and `AvatarGroup` component import
- `services/web-ui/components/AnnotationLayer.tsx` (just written) — `Annotation` interface and `AnnotationLayer` component import
</read_first>

<action>
Create `services/web-ui/components/WarRoomPanel.tsx`:

```typescript
'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X, Users, Zap, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { AvatarGroup, WarRoomParticipant } from './AvatarGroup';
import { AnnotationLayer, Annotation } from './AnnotationLayer';

interface WarRoomPanelProps {
  incidentId: string;
  incidentTitle?: string;
  onClose: () => void;
}

interface WarRoomState {
  participants: WarRoomParticipant[];
  annotations: Annotation[];
  handoff_summary: string | null;
  loading: boolean;
  error: string | null;
}

const HEARTBEAT_INTERVAL_MS = 30_000; // 30 seconds

/**
 * WarRoomPanel — slide-over sheet for multi-operator P0 incident collaboration.
 *
 * On mount:
 *  1. POST /api/proxy/war-room/join to join the war room
 *  2. Connect SSE stream via GET /api/proxy/war-room/stream for live annotation push
 *  3. Start 30s heartbeat interval to maintain presence
 *
 * On unmount: closes SSE connection, clears heartbeat interval.
 */
export function WarRoomPanel({ incidentId, incidentTitle, onClose }: WarRoomPanelProps) {
  const [state, setState] = useState<WarRoomState>({
    participants: [],
    annotations: [],
    handoff_summary: null,
    loading: true,
    error: null,
  });
  const [generatingHandoff, setGeneratingHandoff] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ----- Join war room on mount -----
  const joinWarRoom = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await fetch(
        `/api/proxy/war-room/join?incident_id=${encodeURIComponent(incidentId)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role: 'support' }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `Join failed: ${res.status}`);
      }
      const data = await res.json();
      const warRoom = data.war_room ?? {};
      setState({
        participants: (warRoom.participants as WarRoomParticipant[]) ?? [],
        annotations: (warRoom.annotations as Annotation[]) ?? [],
        handoff_summary: warRoom.handoff_summary ?? null,
        loading: false,
        error: null,
      });
    } catch (err) {
      setState((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to join war room',
      }));
    }
  }, [incidentId]);

  // ----- Connect SSE stream -----
  const connectStream = useCallback(() => {
    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        const res = await fetch(
          `/api/proxy/war-room/stream?incident_id=${encodeURIComponent(incidentId)}`,
          { signal: controller.signal }
        );
        if (!res.ok || !res.body) return;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const payload = JSON.parse(line.slice(6));
                if (payload.type === 'annotation' && payload.annotation) {
                  setState((s) => ({
                    ...s,
                    annotations: [...s.annotations, payload.annotation as Annotation],
                  }));
                }
              } catch {
                // Malformed SSE data — skip
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') {
          console.error('[WarRoomPanel] SSE stream error:', err);
        }
      }
    })();
  }, [incidentId]);

  // ----- Heartbeat -----
  const startHeartbeat = useCallback(() => {
    heartbeatRef.current = setInterval(async () => {
      try {
        await fetch(
          `/api/proxy/war-room/heartbeat?incident_id=${encodeURIComponent(incidentId)}`,
          { method: 'POST' }
        );
      } catch {
        // Heartbeat is best-effort — swallow errors silently
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, [incidentId]);

  useEffect(() => {
    joinWarRoom();
    connectStream();
    startHeartbeat();

    return () => {
      abortRef.current?.abort();
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, [joinWarRoom, connectStream, startHeartbeat]);

  // ----- Annotation added locally (optimistic append for annotations from this client) -----
  function handleAnnotationAdded(annotation: Annotation) {
    setState((s) => ({
      ...s,
      // Avoid duplicate if SSE already pushed this annotation
      annotations: s.annotations.some((a) => a.id === annotation.id)
        ? s.annotations
        : [...s.annotations, annotation],
    }));
  }

  // ----- Generate handoff summary -----
  async function handleGenerateHandoff() {
    setGeneratingHandoff(true);
    setHandoffError(null);
    try {
      const res = await fetch(
        `/api/proxy/war-room/handoff?incident_id=${encodeURIComponent(incidentId)}`,
        { method: 'POST' }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error ?? `Handoff failed: ${res.status}`);
      }
      const data = await res.json();
      setState((s) => ({ ...s, handoff_summary: data.summary ?? null }));
    } catch (err) {
      setHandoffError(err instanceof Error ? err.message : 'Failed to generate handoff');
    } finally {
      setGeneratingHandoff(false);
    }
  }

  return (
    <div
      className="fixed inset-y-0 right-0 z-50 flex flex-col w-[480px] max-w-full shadow-2xl"
      style={{ background: 'var(--bg-canvas)', borderLeft: '1px solid var(--border)' }}
      role="dialog"
      aria-label={`War Room — ${incidentTitle ?? incidentId}`}
    >
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3 shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <Zap className="w-4 h-4 shrink-0" style={{ color: 'var(--accent-red)' }} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
            War Room
          </p>
          <p className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>
            {incidentTitle ?? incidentId}
          </p>
        </div>
        {!state.loading && (
          <AvatarGroup
            participants={state.participants}
            className="shrink-0"
          />
        )}
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close war room">
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden">
        {state.loading ? (
          <div className="p-4 flex flex-col gap-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : state.error ? (
          <div className="p-4">
            <p className="text-sm" style={{ color: 'var(--accent-red)' }}>{state.error}</p>
            <Button size="sm" variant="outline" className="mt-2" onClick={joinWarRoom}>
              Retry
            </Button>
          </div>
        ) : (
          <Tabs defaultValue="notes" className="h-full flex flex-col">
            <TabsList className="mx-4 mt-3 shrink-0 w-auto justify-start">
              <TabsTrigger value="notes" className="text-xs gap-1">
                <FileText className="w-3 h-3" />
                Notes
                {state.annotations.length > 0 && (
                  <Badge
                    variant="secondary"
                    className="ml-1 px-1 py-0 text-[10px]"
                  >
                    {state.annotations.length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="presence" className="text-xs gap-1">
                <Users className="w-3 h-3" />
                Team ({state.participants.length})
              </TabsTrigger>
              <TabsTrigger value="handoff" className="text-xs">
                Handoff
              </TabsTrigger>
            </TabsList>

            {/* Notes tab */}
            <TabsContent value="notes" className="flex-1 overflow-y-auto p-4">
              <AnnotationLayer
                incidentId={incidentId}
                annotations={state.annotations}
                onAnnotationAdded={handleAnnotationAdded}
              />
            </TabsContent>

            {/* Presence tab */}
            <TabsContent value="presence" className="flex-1 overflow-y-auto p-4">
              <div className="flex flex-col gap-2">
                {state.participants.map((p) => (
                  <div
                    key={p.operator_id}
                    className="flex items-center gap-3 rounded-md px-3 py-2"
                    style={{ background: 'color-mix(in srgb, var(--accent-blue) 6%, var(--bg-canvas))', border: '1px solid var(--border)' }}
                  >
                    <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                      {p.display_name || p.operator_id}
                    </span>
                    <Badge
                      variant="outline"
                      className="text-[10px] px-1.5"
                      style={{
                        color: p.role === 'lead' ? 'var(--accent-yellow, #f59e0b)' : 'var(--accent-blue)',
                        borderColor: p.role === 'lead' ? 'var(--accent-yellow, #f59e0b)' : 'var(--accent-blue)',
                      }}
                    >
                      {p.role}
                    </Badge>
                    <span className="ml-auto text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                      joined {new Date(p.joined_at).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            </TabsContent>

            {/* Handoff tab */}
            <TabsContent value="handoff" className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                Generate a structured shift-handoff summary using GPT-4o based on all investigation notes.
              </p>
              <Button
                size="sm"
                onClick={handleGenerateHandoff}
                disabled={generatingHandoff}
                className="self-start"
              >
                {generatingHandoff ? 'Generating…' : 'End my shift — generate handoff'}
              </Button>
              {handoffError && (
                <p className="text-xs" style={{ color: 'var(--accent-red)' }}>{handoffError}</p>
              )}
              {state.handoff_summary && (
                <div
                  className="rounded-md p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-blue) 6%, var(--bg-canvas))',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                  }}
                >
                  {state.handoff_summary}
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  );
}
```
</action>

<acceptance_criteria>
- File `services/web-ui/components/WarRoomPanel.tsx` exists
- `grep "'use client'" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "export function WarRoomPanel" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "HEARTBEAT_INTERVAL_MS = 30_000" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "connectStream" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "joinWarRoom" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "AvatarGroup" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "AnnotationLayer" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "End my shift" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "abortRef.current?.abort()" services/web-ui/components/WarRoomPanel.tsx` exits 0
- `grep "clearInterval" services/web-ui/components/WarRoomPanel.tsx` exits 0
- No hardcoded Tailwind color classes: `grep -E "bg-(red|green|blue|yellow|purple)-[0-9]+" services/web-ui/components/WarRoomPanel.tsx` exits 1
</acceptance_criteria>

---

### Task 5: Add "Open War Room" button to `AlertFeed.tsx`

<read_first>
- `services/web-ui/components/AlertFeed.tsx` — FULL FILE — exact `IncidentSummary` interface, table row rendering, existing `onInvestigate` callback pattern, button placement near "Investigate" button
- `services/web-ui/components/WarRoomPanel.tsx` (just written) — `WarRoomPanelProps` interface for import
</read_first>

<action>
Make 4 targeted changes to `services/web-ui/components/AlertFeed.tsx`:

**Change 1 — Import `WarRoomPanel` and `Shield` icon** (after existing lucide imports):
```typescript
import { Shield } from 'lucide-react';
import { WarRoomPanel } from './WarRoomPanel';
```

**Change 2 — Add `warRoomIncidentId` state** (after existing `useState` hooks at the top of `AlertFeed`):
```typescript
const [warRoomIncidentId, setWarRoomIncidentId] = useState<string | null>(null);
const [warRoomTitle, setWarRoomTitle] = useState<string | undefined>(undefined);
```

**Change 3 — Add "War Room" button in each severity `Sev0`/`Sev1` incident row**, placed immediately after (or before) the existing "Investigate" button. Only show for P0/P1 severity:
```typescript
{(incident.severity === 'Sev0' || incident.severity === 'Sev1') && (
  <Button
    size="sm"
    variant="outline"
    className="text-xs h-6 px-2 flex items-center gap-1"
    style={{ color: 'var(--accent-red)', borderColor: 'var(--accent-red)' }}
    onClick={() => {
      setWarRoomIncidentId(incident.incident_id);
      setWarRoomTitle(incident.title || incident.resource_name || incident.incident_id);
    }}
  >
    <Shield className="w-3 h-3" />
    War Room
  </Button>
)}
```

**Change 4 — Render `WarRoomPanel` when `warRoomIncidentId` is set** (at the end of the component return, after the table/outer div):
```typescript
{warRoomIncidentId && (
  <WarRoomPanel
    incidentId={warRoomIncidentId}
    incidentTitle={warRoomTitle}
    onClose={() => setWarRoomIncidentId(null)}
  />
)}
```
</action>

<acceptance_criteria>
- `grep "WarRoomPanel" services/web-ui/components/AlertFeed.tsx` exits 0
- `grep "warRoomIncidentId" services/web-ui/components/AlertFeed.tsx` exits 0
- `grep "War Room" services/web-ui/components/AlertFeed.tsx` exits 0
- `grep "Sev0.*Sev1\|Sev1.*Sev0" services/web-ui/components/AlertFeed.tsx` exits 0
- `grep "setWarRoomIncidentId" services/web-ui/components/AlertFeed.tsx` exits 0
- `grep "Shield" services/web-ui/components/AlertFeed.tsx` exits 0
</acceptance_criteria>

---

## Verification

```bash
# 1. TypeScript compile check — zero errors
cd services/web-ui && npx tsc --noEmit 2>&1 | head -20

# 2. All proxy routes exist
for route in join annotations stream heartbeat handoff; do
  test -f "services/web-ui/app/api/proxy/war-room/$route/route.ts" && echo "OK: $route" || echo "MISSING: $route"
done

# 3. All components exist
for comp in AvatarGroup AnnotationLayer WarRoomPanel; do
  test -f "services/web-ui/components/$comp.tsx" && echo "OK: $comp" || echo "MISSING: $comp"
done

# 4. No hardcoded Tailwind colors in new component files
for comp in AvatarGroup AnnotationLayer WarRoomPanel; do
  count=$(grep -cE "bg-(red|green|blue|yellow|purple)-[0-9]+" "services/web-ui/components/$comp.tsx" 2>/dev/null || echo 0)
  [ "$count" -eq 0 ] && echo "OK: $comp no hardcoded colors" || echo "FAIL: $comp has $count hardcoded colors"
done

# 5. AlertFeed imports WarRoomPanel
grep "WarRoomPanel" services/web-ui/components/AlertFeed.tsx

# 6. Build passes
cd services/web-ui && npm run build 2>&1 | tail -5
```

## must_haves

- [ ] 5 proxy routes created under `services/web-ui/app/api/proxy/war-room/`: `join`, `annotations`, `stream`, `heartbeat`, `handoff`
- [ ] `stream/route.ts` uses `ReadableStream` passthrough (not `res.json()`) and sets `Content-Type: text/event-stream`
- [ ] `handoff/route.ts` uses `AbortSignal.timeout(45000)` (GPT-4o latency allowance)
- [ ] `AvatarGroup.tsx` exports `WarRoomParticipant` interface; uses `color-mix(in srgb, var(--accent-*) ...)` for badge backgrounds; no hardcoded Tailwind color classes
- [ ] `AnnotationLayer.tsx` has `maxLength={4096}` on Textarea; uses `var(--accent-*)` tokens; exports `Annotation` interface
- [ ] `WarRoomPanel.tsx` has `HEARTBEAT_INTERVAL_MS = 30_000`; clears both SSE AbortController and heartbeat interval in useEffect cleanup
- [ ] `WarRoomPanel.tsx` has 3 tabs: Notes, Team, Handoff; "End my shift — generate handoff" button in Handoff tab
- [ ] `AlertFeed.tsx` has "War Room" button visible only on Sev0/Sev1 incidents; opens `WarRoomPanel` on click
- [ ] `npx tsc --noEmit` exits 0 (no TypeScript errors)
