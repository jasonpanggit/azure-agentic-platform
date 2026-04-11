---
wave: 2
depends_on:
  - 35-1-verification-feedback-loop-PLAN.md
files_modified:
  - services/web-ui/components/VerificationCard.tsx
  - services/web-ui/components/ChatDrawer.tsx
  - services/web-ui/app/api/proxy/approvals/[approvalId]/verification/route.ts
  - services/web-ui/lib/use-verification-poll.ts
autonomous: true
---

# Plan 35-3: "Did it work?" UI Verification Card

## Goal

After a remediation action is executed, show a verification status card in the chat panel. The card appears after a configurable delay, polls the `GET /api/v1/approvals/{id}/verification` endpoint for the verification result, and displays one of four outcome states (RESOLVED/IMPROVED/DEGRADED/TIMEOUT). Includes "Did this fix the issue?" Yes/No prompt for operator confirmation. "Yes" resolves the incident; "No" sends a re-diagnosis message to the agent.

## Derived Requirements

- **LOOP-002:** "Did it work?" UI card appears `POST_REMEDIATION_PROMPT_DELAY_MINUTES` (default 5) after execution, polls verification endpoint, shows result with operator Yes/No confirmation.
- **LOOP-005:** Operator "No" response triggers re-diagnosis message injection into the same Foundry thread.

<threat_model>

### Authentication/Authorization Risks
- **LOW:** The new proxy route `app/api/proxy/approvals/[approvalId]/verification/route.ts` forwards the MSAL Bearer token to the API gateway (same pattern as existing approve/reject proxy routes). Authentication is enforced by the API gateway's `verify_token` dependency.

### Input Validation Risks
- **LOW:** The `approvalId` is URL-path encoded by Next.js. The proxy route does not accept request bodies. No user input beyond the path parameter.

### Data Exposure Risks
- **LOW:** The verification response contains `execution_id`, `approval_id`, `verification_result`, `verified_at`, `resource_id` — all already available in the approval record. No new data exposure.

### High-Severity Threats
- **NONE.**

**Verdict:** No threats. Read-only UI component with authenticated proxy passthrough.

</threat_model>

## Tasks

<task id="35-3-1">
<title>Create verification proxy route</title>
<read_first>
- services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts (existing proxy route pattern — replicate the structure: getApiGatewayUrl, buildUpstreamHeaders, AbortSignal.timeout(15000), error handling)
- services/web-ui/lib/api-gateway.ts (getApiGatewayUrl and buildUpstreamHeaders function signatures)
</read_first>
<action>
Create `services/web-ui/app/api/proxy/approvals/[approvalId]/verification/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/approvals/verification' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/approvals/[approvalId]/verification
 *
 * Proxies verification result polling to the API gateway.
 * Returns 202 with Retry-After when verification is still pending.
 * Returns 200 with RemediationAuditRecord when verification is complete.
 * Returns 404 when no execution record exists.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ approvalId: string }> }
): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { approvalId } = await params;
    log.info('verification poll', { approvalId });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/approvals/${encodeURIComponent(approvalId)}/verification`,
      {
        method: 'GET',
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    if (res.status === 202) {
      const data = await res.json();
      log.debug('verification pending', { approvalId });
      return NextResponse.json(data, {
        status: 202,
        headers: { 'Retry-After': res.headers.get('Retry-After') || '60' },
      });
    }

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { approvalId, status: res.status, detail: errorData?.detail });
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('verification result', { approvalId, result: data?.verification_result });
    return NextResponse.json(data, { status: 200 });
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
- File exists at `services/web-ui/app/api/proxy/approvals/[approvalId]/verification/route.ts`
- grep "getApiGatewayUrl" services/web-ui/app/api/proxy/approvals/\[approvalId\]/verification/route.ts returns 1 match
- grep "buildUpstreamHeaders" services/web-ui/app/api/proxy/approvals/\[approvalId\]/verification/route.ts returns 1 match
- grep "AbortSignal.timeout(15000)" services/web-ui/app/api/proxy/approvals/\[approvalId\]/verification/route.ts returns 1 match
- grep "Retry-After" services/web-ui/app/api/proxy/approvals/\[approvalId\]/verification/route.ts returns at least 1 match
- grep "status: 202" services/web-ui/app/api/proxy/approvals/\[approvalId\]/verification/route.ts returns 1 match
</acceptance_criteria>
</task>

<task id="35-3-2">
<title>Create useVerificationPoll custom hook</title>
<read_first>
- services/web-ui/lib/use-sse.ts (existing custom hook pattern — understand how hooks are structured in this project)
- services/web-ui/components/ChatDrawer.tsx (lines 44-57 — getAccessToken pattern to understand auth token retrieval)
</read_first>
<action>
Create `services/web-ui/lib/use-verification-poll.ts`:

```typescript
'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

interface VerificationResult {
  execution_id: string;
  approval_id: string;
  verification_result: 'RESOLVED' | 'IMPROVED' | 'DEGRADED' | 'TIMEOUT' | null;
  verified_at: string | null;
  resource_id?: string;
  proposed_action?: string;
  rolled_back?: boolean;
  status?: string;
}

interface UseVerificationPollOptions {
  approvalId: string | null;
  executedAt: string | null;
  delayMinutes?: number;
  maxAttempts?: number;
  pollIntervalMs?: number;
  getAccessToken: () => Promise<string | null>;
}

interface UseVerificationPollReturn {
  result: VerificationResult | null;
  isPolling: boolean;
  error: string | null;
}

/**
 * Custom hook that polls the verification endpoint after a remediation execution.
 *
 * Starts polling `delayMinutes` after `executedAt` timestamp. Polls every
 * `pollIntervalMs` (default 30s) for up to `maxAttempts` (default 20).
 * Stops when verification_result is non-null or max attempts reached.
 */
export function useVerificationPoll({
  approvalId,
  executedAt,
  delayMinutes = 5,
  maxAttempts = 20,
  pollIntervalMs = 30000,
  getAccessToken,
}: UseVerificationPollOptions): UseVerificationPollReturn {
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    if (!approvalId) return;

    attemptRef.current += 1;
    if (attemptRef.current > maxAttempts) {
      setIsPolling(false);
      setError('Verification polling timed out after max attempts');
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }

    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(
        `/api/proxy/approvals/${encodeURIComponent(approvalId)}/verification`,
        { method: 'GET', headers }
      );

      if (res.status === 202) {
        // Still pending — continue polling
        return;
      }

      if (res.status === 404) {
        // No execution record yet — continue polling
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data?.error || `Verification check failed: ${res.status}`);
        return;
      }

      const data: VerificationResult = await res.json();
      if (data.verification_result !== null && data.verification_result !== undefined) {
        setResult(data);
        setIsPolling(false);
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    } catch (err) {
      // Transient error — continue polling
      console.warn('Verification poll failed:', err);
    }
  }, [approvalId, maxAttempts, getAccessToken]);

  useEffect(() => {
    if (!approvalId || !executedAt) return;

    // Calculate delay before first poll
    const executedTime = new Date(executedAt).getTime();
    const pollStartTime = executedTime + delayMinutes * 60 * 1000;
    const now = Date.now();
    const delayMs = Math.max(pollStartTime - now, 0);

    attemptRef.current = 0;
    setResult(null);
    setError(null);

    // Start polling after delay
    timerRef.current = setTimeout(() => {
      setIsPolling(true);
      poll(); // First poll immediately
      intervalRef.current = setInterval(poll, pollIntervalMs);
    }, delayMs);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (intervalRef.current) clearInterval(intervalRef.current);
      setIsPolling(false);
    };
  }, [approvalId, executedAt, delayMinutes, pollIntervalMs, poll]);

  return { result, isPolling, error };
}
```
</action>
<acceptance_criteria>
- File exists at `services/web-ui/lib/use-verification-poll.ts`
- grep "useVerificationPoll" services/web-ui/lib/use-verification-poll.ts returns at least 3 matches (export + function name + interface name)
- grep "verification_result" services/web-ui/lib/use-verification-poll.ts returns at least 2 matches
- grep "RESOLVED.*IMPROVED.*DEGRADED.*TIMEOUT" services/web-ui/lib/use-verification-poll.ts returns 1 match
- grep "pollIntervalMs" services/web-ui/lib/use-verification-poll.ts returns at least 2 matches
- grep "maxAttempts" services/web-ui/lib/use-verification-poll.ts returns at least 2 matches
</acceptance_criteria>
</task>

<task id="35-3-3">
<title>Create VerificationCard component</title>
<read_first>
- services/web-ui/components/ProposalCard.tsx (full file — follow the same component pattern: Card, CardContent, Badge, Button from shadcn/ui, semantic CSS tokens)
- services/web-ui/lib/use-verification-poll.ts (UseVerificationPollReturn interface)
- CLAUDE.md (Frontend Patterns section — CSS semantic token system: var(--accent-*), never hardcoded Tailwind colors)
</read_first>
<action>
Create `services/web-ui/components/VerificationCard.tsx`:

```typescript
'use client';

import React, { useState, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CheckCircle, TrendingDown, AlertTriangle, Clock, Loader2 } from 'lucide-react';

interface VerificationCardProps {
  approvalId: string;
  incidentId: string;
  threadId: string;
  verificationResult: 'RESOLVED' | 'IMPROVED' | 'DEGRADED' | 'TIMEOUT' | null;
  isPolling: boolean;
  proposedAction: string;
  resourceId: string;
  rolledBack?: boolean;
  getAccessToken: () => Promise<string | null>;
  onChatMessage?: (message: string) => void;
}

const RESULT_CONFIG = {
  RESOLVED: {
    icon: CheckCircle,
    color: 'var(--accent-green)',
    bgColor: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
    label: 'Resolved',
    message: 'The remediation action resolved the issue.',
  },
  IMPROVED: {
    icon: TrendingDown,
    color: 'var(--accent-blue)',
    bgColor: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
    label: 'Improved',
    message: 'Resource health improved but may not be fully resolved.',
  },
  DEGRADED: {
    icon: AlertTriangle,
    color: 'var(--accent-red)',
    bgColor: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
    label: 'Degraded',
    message: 'Resource degraded after action. Auto-rollback was triggered.',
  },
  TIMEOUT: {
    icon: Clock,
    color: 'var(--accent-orange)',
    bgColor: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
    label: 'Timeout',
    message: 'Verification timed out. Resource health status unknown.',
  },
} as const;

export function VerificationCard({
  approvalId,
  incidentId,
  threadId,
  verificationResult,
  isPolling,
  proposedAction,
  resourceId,
  rolledBack,
  getAccessToken,
  onChatMessage,
}: VerificationCardProps) {
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [reDiagnosing, setReDiagnosing] = useState(false);

  const handleYes = useCallback(async () => {
    setResolving(true);
    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`/api/proxy/incidents/${encodeURIComponent(incidentId)}/resolve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          summary: `Resolved via ${proposedAction} — verification confirmed by operator.`,
          resolution: `Action: ${proposedAction} on ${resourceId}. Operator confirmed resolution.`,
        }),
      });

      if (res.ok) {
        setResolved(true);
      }
    } catch {
      // Non-critical — operator can resolve manually
    } finally {
      setResolving(false);
    }
  }, [getAccessToken, incidentId, proposedAction, resourceId]);

  const handleNo = useCallback(() => {
    if (onChatMessage) {
      setReDiagnosing(true);
      onChatMessage(
        `The operator reports the issue persists after ${proposedAction}. ` +
        `Resource: ${resourceId}. Re-diagnose the problem and propose an alternative approach.`
      );
    }
  }, [onChatMessage, proposedAction, resourceId]);

  // Polling state — show spinner
  if (isPolling && !verificationResult) {
    return (
      <Card
        className="max-w-[90%] self-start p-4 mb-2"
        style={{
          border: '1px solid var(--border)',
          borderLeft: '4px solid var(--accent-blue)',
          background: 'var(--bg-subtle)',
          borderRadius: '8px',
        }}
      >
        <CardContent className="p-0">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" style={{ color: 'var(--accent-blue)' }} />
            <span className="text-sm font-semibold">Verifying remediation result...</span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Checking if the action resolved the issue. This may take a few minutes.
          </p>
        </CardContent>
      </Card>
    );
  }

  // No result yet and not polling — don't render
  if (!verificationResult) return null;

  const config = RESULT_CONFIG[verificationResult];
  const Icon = config.icon;

  return (
    <Card
      className="max-w-[90%] self-start p-4 mb-2"
      style={{
        border: '1px solid var(--border)',
        borderLeft: `4px solid ${config.color}`,
        background: 'var(--bg-subtle)',
        borderRadius: '8px',
      }}
    >
      <CardContent className="p-0">
        <div className="flex items-center gap-2 mb-2">
          <Icon className="h-5 w-5" style={{ color: config.color }} />
          <Badge
            style={{
              background: config.bgColor,
              color: config.color,
              border: 'none',
            }}
          >
            {config.label}
          </Badge>
          <span className="font-semibold text-sm">{config.message}</span>
        </div>

        {rolledBack && verificationResult === 'DEGRADED' && (
          <p className="text-sm text-muted-foreground mb-2">
            Auto-rollback has been triggered to restore the previous state.
          </p>
        )}

        {resolved ? (
          <p className="text-sm" style={{ color: 'var(--accent-green)' }}>
            Incident marked as resolved.
          </p>
        ) : reDiagnosing ? (
          <p className="text-sm text-muted-foreground">
            Re-diagnosis requested. The agent is investigating...
          </p>
        ) : (
          <>
            <p className="text-sm font-medium mt-2 mb-2">Did this remediation resolve the issue?</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleYes}
                disabled={resolving}
                style={{ background: 'var(--accent-green)', color: '#FFFFFF', border: 'none' }}
              >
                {resolving ? 'Resolving...' : 'Yes, resolved'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleNo}
                style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}
              >
                No, still an issue
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
```
</action>
<acceptance_criteria>
- File exists at `services/web-ui/components/VerificationCard.tsx`
- grep "VerificationCard" services/web-ui/components/VerificationCard.tsx returns at least 3 matches
- grep "RESOLVED\|IMPROVED\|DEGRADED\|TIMEOUT" services/web-ui/components/VerificationCard.tsx returns at least 4 matches
- grep "Did this remediation resolve the issue" services/web-ui/components/VerificationCard.tsx returns 1 match
- grep "var(--accent-green)" services/web-ui/components/VerificationCard.tsx returns at least 1 match
- grep "var(--accent-red)" services/web-ui/components/VerificationCard.tsx returns at least 1 match
- grep "color-mix" services/web-ui/components/VerificationCard.tsx returns at least 2 matches (dark-mode-safe badge pattern)
- grep "onChatMessage" services/web-ui/components/VerificationCard.tsx returns at least 2 matches
- `setReDiagnosing(true)` appears INSIDE the `if (onChatMessage)` guard block — not before it
- No hardcoded Tailwind color classes like bg-green-100 or text-red-700 in the file: grep "bg-green\|bg-red\|text-green\|text-red" services/web-ui/components/VerificationCard.tsx returns 0 matches
</acceptance_criteria>
</task>

<task id="35-3-4">
<title>Wire VerificationCard into ChatDrawer</title>
<read_first>
- services/web-ui/components/ChatDrawer.tsx (full file — understand message state management, how ProposalCard is rendered, handleSend function, handleApprove function signature and how approvalGate is stored in messages)
- services/web-ui/components/VerificationCard.tsx (props interface)
- services/web-ui/lib/use-verification-poll.ts (useVerificationPoll hook interface)
</read_first>
<action>
Modify `services/web-ui/components/ChatDrawer.tsx`:

1. **Add imports** at the top (after the ProposalCard import):
```typescript
import { VerificationCard } from './VerificationCard';
import { useVerificationPoll } from '@/lib/use-verification-poll';
```

2. **Add verification tracking state** inside the `ChatDrawer` component, after the existing state declarations (after line ~42):
```typescript
const [executedApproval, setExecutedApproval] = useState<{
  incidentId: string;
  action: string;
  resourceIds: string[];
} | null>(null);
```

3. **Initialize the useVerificationPoll hook** after the state declaration:
```typescript
const { result: verificationResult, isPolling: isVerificationPolling } = useVerificationPoll({
  approvalId: executedApproval?.approvalId ?? null,
  executedAt: executedApproval?.executedAt ?? null,
  delayMinutes: 5,
  getAccessToken,
});
```

4. **Track execution events from the handleApprove callback.** Instead of receiving full approval context directly in `handleApprove`, find the `approvalGate` in the messages state by `approvalId`:

In the existing `handleApprove` handler (or after the successful approval API call), add:
```typescript
// Track for verification polling (LOOP-002)
// Find the approval gate context from the messages state
const approvalMsg = messages.find(m => m.approvalGate?.id === approvalId);
const gate = approvalMsg?.approvalGate;
if (gate) {
  setExecutedApproval({
    approvalId: gate.id || approvalId,
    incidentId: gate.incident_id,
    executedAt: new Date().toISOString(),
    action: gate.proposal.action,
    resourceIds: gate.proposal.target_resources,
  });
}
```

5. **Create a handler for sending re-diagnosis chat messages** (for the "No" button). Instead of duplicating the send logic, call the existing `handleSend` directly:
```typescript
const handleVerificationChatMessage = useCallback((message: string) => {
  // Inject re-diagnosis message into the existing chat flow
  // Uses the existing handleSend path to avoid logic duplication
  setInput(message);
  // Defer to next tick so React batches the input state update
  setTimeout(() => handleSend(), 0);
}, [handleSend, setInput]);
```

**LOOP-005 note:** If `handleSend` does not accept a `message` parameter directly, use the `setInput` + `handleSend()` pattern above. If `handleSend(message: string)` is a valid signature, use `handleSend(message)` directly instead.

6. **Render VerificationCard in the message area.** After the message list rendering (after the messages.map block, before the messagesEndRef div), add:

**LOOP-005 critical:** When the "No" button triggers re-diagnosis, the request body MUST include `threadId: incidentThreadId` (the thread ID from the incident record) to inject into the existing Foundry thread rather than creating an orphan thread. Verify that the `handleSend` / chat proxy call uses the `threadId` state variable already maintained by ChatDrawer.

```typescript
{executedApproval && (
  <VerificationCard
    approvalId={executedApproval.approvalId}
    incidentId={executedApproval.incidentId}
    threadId={threadId || ''}
    verificationResult={verificationResult?.verification_result ?? null}
    isPolling={isVerificationPolling}
    proposedAction={executedApproval.action}
    resourceId={executedApproval.resourceIds?.[0] || ''}
    rolledBack={verificationResult?.rolled_back}
    getAccessToken={getAccessToken}
    onChatMessage={handleVerificationChatMessage}
  />
)}
```
</action>
<acceptance_criteria>
- grep "VerificationCard" services/web-ui/components/ChatDrawer.tsx returns at least 2 matches (import + JSX)
- grep "useVerificationPoll" services/web-ui/components/ChatDrawer.tsx returns at least 2 matches (import + usage)
- grep "executedApproval" services/web-ui/components/ChatDrawer.tsx returns at least 3 matches
- grep "verificationResult" services/web-ui/components/ChatDrawer.tsx returns at least 2 matches
- grep "handleVerificationChatMessage" services/web-ui/components/ChatDrawer.tsx returns at least 2 matches
- grep "messages.find(m => m.approvalGate" services/web-ui/components/ChatDrawer.tsx returns at least 1 match (approval gate lookup from messages state)
- The handleVerificationChatMessage does NOT duplicate the fetch('/api/proxy/chat') logic — it delegates to handleSend
- Running `cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit` exits 0 (no TypeScript errors)
</acceptance_criteria>
</task>

<task id="35-3-5">
<title>Create incidents resolve proxy route</title>
<read_first>
- services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts (existing POST proxy pattern)
- services/web-ui/lib/api-gateway.ts (getApiGatewayUrl, buildUpstreamHeaders)
</read_first>
<action>
Check if `services/web-ui/app/api/proxy/incidents/[incidentId]/resolve/route.ts` already exists. If not, create it:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/incidents/resolve' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/incidents/[incidentId]/resolve
 *
 * Proxies incident resolution to the API gateway.
 * Called by VerificationCard "Yes, resolved" button (LOOP-002).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ incidentId: string }> }
): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { incidentId } = await params;
    const body = await request.json();
    log.info('resolve incident', { incidentId });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/resolve`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { incidentId, status: res.status, detail: errorData?.detail });
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('incident resolved', { incidentId });
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

**LOOP-005 implementation note:** When the "No" button in VerificationCard triggers `onChatMessage`, the `handleVerificationChatMessage` callback in ChatDrawer calls `handleSend()`, which sends to `/api/proxy/chat` with the body including `threadId` from ChatDrawer state. This ensures the re-diagnosis message is injected into the existing Foundry thread (the incident's thread) rather than creating an orphan thread. Verify that `handleSend` includes `thread_id: threadId` in its fetch body — this is the existing ChatDrawer pattern.
</action>
<acceptance_criteria>
- File exists at `services/web-ui/app/api/proxy/incidents/[incidentId]/resolve/route.ts`
- grep "getApiGatewayUrl" services/web-ui/app/api/proxy/incidents/\[incidentId\]/resolve/route.ts returns 1 match
- grep "incidents.*resolve" services/web-ui/app/api/proxy/incidents/\[incidentId\]/resolve/route.ts returns at least 1 match
- grep "LOOP-002" services/web-ui/app/api/proxy/incidents/\[incidentId\]/resolve/route.ts returns 1 match
</acceptance_criteria>
</task>

<task id="35-3-6">
<title>Verify TypeScript build passes</title>
<read_first>
- services/web-ui/components/VerificationCard.tsx (verify no type errors)
- services/web-ui/components/ChatDrawer.tsx (verify no type errors from new additions)
- services/web-ui/lib/use-verification-poll.ts (verify types)
</read_first>
<action>
Run TypeScript check and fix any type errors:

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

If errors are found, fix them in the respective files. Common issues to watch for:
- `useState` type inference on `executedApproval`
- `useCallback` dependency array completeness
- `params` Promise type for route handlers (Next.js 15 pattern)
- `handleSend` may need a message parameter or the `setInput` + `setTimeout` pattern

Also run:
```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npm run build
```

Both must exit 0.
</action>
<acceptance_criteria>
- `cd services/web-ui && npx tsc --noEmit` exits 0
- `cd services/web-ui && npm run build` exits 0
</acceptance_criteria>
</task>

## Verification

```bash
# 1. New files exist
ls services/web-ui/components/VerificationCard.tsx
ls services/web-ui/lib/use-verification-poll.ts
ls services/web-ui/app/api/proxy/approvals/\[approvalId\]/verification/route.ts
ls services/web-ui/app/api/proxy/incidents/\[incidentId\]/resolve/route.ts

# 2. VerificationCard wired into ChatDrawer
grep "VerificationCard\|useVerificationPoll\|executedApproval" services/web-ui/components/ChatDrawer.tsx

# 3. Approval gate lookup from messages state (not hardcoded)
grep "messages.find(m => m.approvalGate" services/web-ui/components/ChatDrawer.tsx

# 4. setReDiagnosing inside onChatMessage guard
grep -A1 "if (onChatMessage)" services/web-ui/components/VerificationCard.tsx | grep "setReDiagnosing"

# 5. Semantic CSS tokens (no hardcoded colors)
grep "bg-green-\|bg-red-\|text-green-\|text-red-" services/web-ui/components/VerificationCard.tsx || echo "PASS: no hardcoded Tailwind colors"

# 6. TypeScript build passes
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit && echo "TSC PASS"
```

## must_haves

- [ ] `VerificationCard.tsx` component renders four verification states (RESOLVED/IMPROVED/DEGRADED/TIMEOUT) with appropriate icons and colors
- [ ] "Did this remediation resolve the issue?" Yes/No prompt appears on the card
- [ ] "Yes" button calls `POST /api/proxy/incidents/{id}/resolve`
- [ ] "No" button sends a re-diagnosis chat message via the existing chat flow (delegates to `handleSend`, not duplicated fetch logic)
- [ ] `setReDiagnosing(true)` is inside the `if (onChatMessage)` guard block, not before it
- [ ] `handleApprove` finds the approval gate context from `messages.find(m => m.approvalGate?.id === approvalId)` — does not assume full context is passed as a parameter
- [ ] Re-diagnosis chat message includes `threadId` in the request body (via existing `handleSend` which uses ChatDrawer's `threadId` state) to inject into the existing Foundry thread (LOOP-005)
- [ ] `useVerificationPoll` hook polls `GET /api/proxy/approvals/{id}/verification` with configurable delay and max attempts
- [ ] Verification proxy route at `app/api/proxy/approvals/[approvalId]/verification/route.ts` passes through auth headers
- [ ] Incidents resolve proxy route at `app/api/proxy/incidents/[incidentId]/resolve/route.ts` exists
- [ ] No hardcoded Tailwind color classes — all colors use semantic CSS tokens
- [ ] TypeScript build (`tsc --noEmit`) passes with zero errors
