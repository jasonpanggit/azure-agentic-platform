---
wave: 3
depends_on: [53-1-PLAN.md, 53-2-PLAN.md]
files_modified:
  - services/teams-bot/src/services/war-room.ts
  - services/teams-bot/src/cards/war-room-card.ts
  - services/teams-bot/src/routes/notify.ts
  - services/teams-bot/src/types.ts
  - services/teams-bot/src/__tests__/war-room.test.ts
autonomous: true
---

# Plan 53-3: Teams Bot War Room Integration — Thread Creation + Bidirectional Message Sync

## Goal

Extend the Teams bot to: (1) create a dedicated Teams channel thread when an operator joins a war room (`war_room_created` card type), (2) forward bidirectional messages between the Teams war room thread and the API gateway war room annotations, and (3) add unit tests covering the new card builder, the new route handler logic, and the message-sync service. This completes the Phase 53 success metric of cross-surface collaboration.

## Context

The Teams bot is a TypeScript Express app (`services/teams-bot/src/`). All new card types follow the established pattern in `notify.ts` and `cards/alert-card.ts`. The war room Teams thread is created by posting an Adaptive Card to the existing channel (same as alert cards) — the Bot Framework `sendActivity` call returns a `messageId` used as the `teams_thread_id` to store back to the API gateway war room document. Bidirectional sync is one-directional here: Teams → API gateway (annotations). The reverse (API gateway SSE → Teams) is done by the existing notify route — a new `war_room_annotation` card type posts the annotation text as a message reply.

The `createTeamsWarRoomThread` function in the new `war-room.ts` service wraps `sendProactiveCard()` (already exported from `proactive.ts`) and POSTs the returned `messageId` back to `POST /api/v1/incidents/{id}/war-room/annotations` so the Teams thread ID appears in the war room timeline.

Bot Framework `onMessage` in `bot.ts` already processes incoming text messages and routes them to the Foundry orchestrator. A new branch detects when a message arrives from a Teams thread identified as a war room thread (by looking up `context.activity.conversation.id` in a `WarRoomThreadRegistry` in-memory map) and instead POSTs to the API gateway as an annotation — bypassing the orchestrator.

<threat_model>
## Security Threat Assessment

**1. `teams_thread_id` storage**: The messageId returned by `sendProactiveCard` is stored in the API gateway war room document via `POST /api/v1/incidents/{id}/war-room/annotations` with a synthetic annotation. This call goes through the gateway's internal service-to-service path — no user input controls the annotation content, only the bot's own messageId string.

**2. `WarRoomThreadRegistry` in-memory map**: Maps `teams_conversation_id` → `incident_id`. Populated on war room creation, never populated from user input. A Teams message arriving in a war room thread uses this lookup — the `incident_id` comes from the registry, not from the Teams message body. No injection risk.

**3. Message forwarding from Teams to war room**: The operator's Teams message is used verbatim as annotation `content`. The API gateway enforces `maxLength: 4096` on annotations and sanitizes storage (Cosmos). The Teams message is plain text (Adaptive Card Action.Execute messages are processed by the bot, not forwarded as HTML).

**4. Card `war_room_created` payload**: Validated against the existing `NotifyRequest.payload` shape — same `if (!body.payload)` pre-flight as all other card types. The `incident_id` field in the payload is a string validated by Pydantic on the Python side before this card is ever sent.

**5. `gateway-client.ts` API calls**: Uses the existing `GatewayClient` class (already in `services/teams-bot/src/services/gateway-client.ts`) with the `GATEWAY_INTERNAL_URL` environment variable — same internal service mesh used by escalation and outcome cards. No new auth surfaces.
</threat_model>

---

## Tasks

### Task 1: Add war room types to `services/teams-bot/src/types.ts`

<read_first>
- `services/teams-bot/src/types.ts` — FULL FILE — existing `NotifyRequest`, `NotifyResponse`, card payload types; `VALID_CARD_TYPES` is a const array in `notify.ts` (not in types.ts); check if payload types are defined here or inline in notify.ts
</read_first>

<action>
Add 2 new payload type interfaces to `services/teams-bot/src/types.ts`:

```typescript
/** Payload for war_room_created card — sent when an operator joins a P0 incident war room */
export interface WarRoomCreatedPayload {
  incident_id: string;
  incident_title?: string;
  severity: string;
  resource_name?: string;
  participants: Array<{
    operator_id: string;
    display_name: string;
    role: string;
  }>;
  /** Deep link to the incident in the Web UI */
  incident_url?: string;
}

/** Payload for war_room_annotation card — syncs a new annotation to the Teams thread */
export interface WarRoomAnnotationPayload {
  incident_id: string;
  incident_title?: string;
  annotation: {
    id: string;
    operator_id: string;
    display_name: string;
    content: string;
    created_at: string;
    trace_event_id: string | null;
  };
}
```
</action>

<acceptance_criteria>
- `grep "export interface WarRoomCreatedPayload" services/teams-bot/src/types.ts` exits 0
- `grep "export interface WarRoomAnnotationPayload" services/teams-bot/src/types.ts` exits 0
- `grep "incident_id: string" services/teams-bot/src/types.ts` exits 0
- `npx tsc --noEmit -p services/teams-bot/tsconfig.json 2>&1 | head -5` shows no errors from types.ts
</acceptance_criteria>

---

### Task 2: Create `services/teams-bot/src/cards/war-room-card.ts`

<read_first>
- `services/teams-bot/src/cards/alert-card.ts` — FULL FILE — exact Adaptive Card v1.5 `$schema` + `type: "AdaptiveCard"` + `version: "1.5"` structure, `ColumnSet` layout, `Action.OpenUrl` pattern
- `services/teams-bot/src/cards/outcome-card.ts` — body + actions structure with `TextBlock` elements and fact sets
- `services/teams-bot/src/types.ts` — `WarRoomCreatedPayload` and `WarRoomAnnotationPayload` just added
</read_first>

<action>
Create `services/teams-bot/src/cards/war-room-card.ts`:

```typescript
import type { WarRoomCreatedPayload, WarRoomAnnotationPayload } from '../types';

/**
 * Build an Adaptive Card for war room creation / operator join events.
 *
 * Schema: Adaptive Card v1.5
 * Layout: header row (⚡ WAR ROOM badge + incident title) + fact set + action buttons
 */
export function buildWarRoomCreatedCard(
  payload: WarRoomCreatedPayload
): Record<string, unknown> {
  const participantNames = payload.participants
    .map((p) => `${p.display_name || p.operator_id} (${p.role})`)
    .join(', ') || 'None yet';

  const facts = [
    { title: 'Incident', value: payload.incident_id },
    { title: 'Severity', value: payload.severity },
    ...(payload.resource_name ? [{ title: 'Resource', value: payload.resource_name }] : []),
    { title: 'Participants', value: participantNames },
  ];

  const actions: Record<string, unknown>[] = [];
  if (payload.incident_url) {
    actions.push({
      type: 'Action.OpenUrl',
      title: 'Open Incident',
      url: payload.incident_url,
    });
  }
  actions.push({
    type: 'Action.OpenUrl',
    title: 'Open War Room',
    url: payload.incident_url
      ? `${payload.incident_url}?war_room=1`
      : `https://aap.example.com/incidents/${payload.incident_id}?war_room=1`,
  });

  return {
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    type: 'AdaptiveCard',
    version: '1.5',
    body: [
      {
        type: 'ColumnSet',
        columns: [
          {
            type: 'Column',
            width: 'auto',
            items: [
              {
                type: 'TextBlock',
                text: '⚡',
                size: 'Large',
              },
            ],
          },
          {
            type: 'Column',
            width: 'stretch',
            items: [
              {
                type: 'TextBlock',
                text: `WAR ROOM — ${payload.incident_title ?? payload.incident_id}`,
                weight: 'Bolder',
                size: 'Medium',
                wrap: true,
              },
              {
                type: 'TextBlock',
                text: `P0 Incident · Multi-operator collaboration active`,
                size: 'Small',
                isSubtle: true,
                wrap: true,
              },
            ],
          },
        ],
      },
      {
        type: 'FactSet',
        facts,
      },
    ],
    actions,
  };
}

/**
 * Build an Adaptive Card for a new war room annotation / investigation note.
 * Posted as a reply to the Teams war room thread.
 */
export function buildWarRoomAnnotationCard(
  payload: WarRoomAnnotationPayload
): Record<string, unknown> {
  const { annotation } = payload;
  const author = annotation.display_name || annotation.operator_id;
  const time = new Date(annotation.created_at).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  return {
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    type: 'AdaptiveCard',
    version: '1.5',
    body: [
      {
        type: 'ColumnSet',
        columns: [
          {
            type: 'Column',
            width: 'auto',
            items: [
              {
                type: 'TextBlock',
                text: '📝',
              },
            ],
          },
          {
            type: 'Column',
            width: 'stretch',
            items: [
              {
                type: 'TextBlock',
                text: `**${author}** · ${time}`,
                size: 'Small',
                wrap: true,
              },
              {
                type: 'TextBlock',
                text: annotation.content,
                wrap: true,
                size: 'Small',
              },
              ...(annotation.trace_event_id
                ? [
                    {
                      type: 'TextBlock',
                      text: `📌 Pinned to trace event: ${annotation.trace_event_id}`,
                      size: 'Small',
                      isSubtle: true,
                      wrap: true,
                    },
                  ]
                : []),
            ],
          },
        ],
      },
    ],
  };
}
```
</action>

<acceptance_criteria>
- File `services/teams-bot/src/cards/war-room-card.ts` exists
- `grep "export function buildWarRoomCreatedCard" services/teams-bot/src/cards/war-room-card.ts` exits 0
- `grep "export function buildWarRoomAnnotationCard" services/teams-bot/src/cards/war-room-card.ts` exits 0
- `grep '"version": "1.5"' services/teams-bot/src/cards/war-room-card.ts` exits 0
- `grep 'WAR ROOM' services/teams-bot/src/cards/war-room-card.ts` exits 0
- `grep 'Action.OpenUrl' services/teams-bot/src/cards/war-room-card.ts` exits 0
- `grep 'trace_event_id' services/teams-bot/src/cards/war-room-card.ts` exits 0
</acceptance_criteria>

---

### Task 3: Create `services/teams-bot/src/services/war-room.ts`

<read_first>
- `services/teams-bot/src/services/proactive.ts` — FULL FILE — `sendProactiveCard`, `sendProactiveText` signatures; `hasConversationReference` guard pattern
- `services/teams-bot/src/services/gateway-client.ts` — FULL FILE — `GatewayClient` class, `postAnnotation` or existing POST methods; if no annotation method exists, use the same `fetch` + `GATEWAY_INTERNAL_URL` pattern to add one inline
- `services/teams-bot/src/types.ts` — `WarRoomCreatedPayload`, `WarRoomAnnotationPayload`
</read_first>

<action>
Create `services/teams-bot/src/services/war-room.ts`:

```typescript
/**
 * War Room Teams Integration Service (Phase 53)
 *
 * Handles:
 * 1. Creating a Teams war room thread (Adaptive Card in the configured channel)
 * 2. WarRoomThreadRegistry — maps Teams conversation IDs to incident IDs for
 *    bidirectional message routing in bot.ts
 * 3. Forwarding incoming Teams messages from war room threads to API gateway
 *    as war room annotations
 */

import { sendProactiveCard } from './proactive';
import { buildWarRoomCreatedCard, buildWarRoomAnnotationCard } from '../cards/war-room-card';
import type { WarRoomCreatedPayload, WarRoomAnnotationPayload } from '../types';

const GATEWAY_INTERNAL_URL = process.env.GATEWAY_INTERNAL_URL ?? '';

// ---------------------------------------------------------------------------
// WarRoomThreadRegistry
// ---------------------------------------------------------------------------
// In-memory map: teamsConversationId → incidentId
// A Teams reply thread gets the same conversationId as the parent channel post
// IF you use a reply-chain flow. For simplicity here we track the messageId
// returned by sendProactiveCard as a secondary lookup key.
const _registry = new Map<string, string>();

export function registerWarRoomThread(teamsMessageId: string, incidentId: string): void {
  _registry.set(teamsMessageId, incidentId);
}

export function lookupWarRoomThread(teamsMessageId: string): string | undefined {
  return _registry.get(teamsMessageId);
}

/** For testing — clear registry state. */
export function _resetRegistry(): void {
  _registry.clear();
}

// ---------------------------------------------------------------------------
// Create Teams war room thread
// ---------------------------------------------------------------------------

export interface CreateWarRoomThreadResult {
  ok: boolean;
  messageId?: string;
  error?: string;
}

/**
 * Post a WAR ROOM card to the Teams channel and register the messageId in the
 * WarRoomThreadRegistry so incoming replies route to the correct war room.
 *
 * Returns the messageId if successful; that ID should be stored in the war room
 * doc as `teams_thread_id` for future reference.
 */
export async function createTeamsWarRoomThread(
  payload: WarRoomCreatedPayload
): Promise<CreateWarRoomThreadResult> {
  const card = buildWarRoomCreatedCard(payload);
  const result = await sendProactiveCard(card);

  if (!result.ok || !result.messageId) {
    return { ok: false, error: 'Failed to send war room card — bot may not be installed' };
  }

  registerWarRoomThread(result.messageId, payload.incident_id);
  console.log(
    `[war-room] Teams thread created | incident_id=${payload.incident_id} message_id=${result.messageId}`
  );

  return { ok: true, messageId: result.messageId };
}

// ---------------------------------------------------------------------------
// Sync Teams message → API gateway annotation
// ---------------------------------------------------------------------------

export interface SyncMessageResult {
  ok: boolean;
  annotationId?: string;
  error?: string;
}

/**
 * Forward a plain-text Teams message from a war room thread to the API gateway
 * as a war room annotation.
 *
 * Called from bot.ts when an incoming Teams message is identified as belonging
 * to a war room thread via WarRoomThreadRegistry.
 */
export async function syncTeamsMessageToWarRoom(
  incidentId: string,
  operatorId: string,
  displayName: string,
  content: string
): Promise<SyncMessageResult> {
  if (!GATEWAY_INTERNAL_URL) {
    console.warn('[war-room] GATEWAY_INTERNAL_URL not set — cannot sync message');
    return { ok: false, error: 'GATEWAY_INTERNAL_URL not configured' };
  }

  try {
    const res = await fetch(
      `${GATEWAY_INTERNAL_URL}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room/annotations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: content.slice(0, 4096),  // enforce max length
          display_name: displayName,
          trace_event_id: null,
        }),
        signal: AbortSignal.timeout(10000),
      }
    );

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      return { ok: false, error: errData?.error ?? `Gateway error: ${res.status}` };
    }

    const data = await res.json();
    const annotationId: string = data?.annotation?.id ?? '';
    console.log(
      `[war-room] Teams message synced | incident_id=${incidentId} annotation_id=${annotationId}`
    );
    return { ok: true, annotationId };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error('[war-room] Failed to sync Teams message:', message);
    return { ok: false, error: message };
  }
}

// ---------------------------------------------------------------------------
// Post annotation card back to Teams (API gateway → Teams)
// ---------------------------------------------------------------------------

/**
 * Post a war room annotation Adaptive Card to the Teams channel.
 * Called from the /teams/internal/notify route when card_type = "war_room_annotation".
 */
export async function postAnnotationToTeams(
  payload: WarRoomAnnotationPayload
): Promise<{ ok: boolean; messageId?: string }> {
  const card = buildWarRoomAnnotationCard(payload);
  return sendProactiveCard(card);
}
```
</action>

<acceptance_criteria>
- File `services/teams-bot/src/services/war-room.ts` exists
- `grep "export function createTeamsWarRoomThread" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "export function syncTeamsMessageToWarRoom" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "export function postAnnotationToTeams" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "registerWarRoomThread" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "lookupWarRoomThread" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "_resetRegistry" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "slice(0, 4096)" services/teams-bot/src/services/war-room.ts` exits 0
- `grep "GATEWAY_INTERNAL_URL" services/teams-bot/src/services/war-room.ts` exits 0
</acceptance_criteria>

---

### Task 4: Wire `war_room_created` and `war_room_annotation` into `routes/notify.ts`

<read_first>
- `services/teams-bot/src/routes/notify.ts` — FULL FILE — `VALID_CARD_TYPES` const array, switch/if-else block dispatching to card builders, `sendProactiveCard(card)` call at end of handler
- `services/teams-bot/src/services/war-room.ts` (just written) — `createTeamsWarRoomThread`, `postAnnotationToTeams` imports
</read_first>

<action>
Make 3 targeted changes to `services/teams-bot/src/routes/notify.ts`:

**Change 1 — Extend `VALID_CARD_TYPES`** (add two new entries to the const array):
```typescript
const VALID_CARD_TYPES = [
  "alert",
  "approval",
  "outcome",
  "reminder",
  "sop_notification",
  "sop_escalation",
  "sop_summary",
  "war_room_created",      // Phase 53: war room creation notification
  "war_room_annotation",   // Phase 53: sync annotation to Teams thread
] as const;
```

**Change 2 — Add imports** (after existing card builder imports):
```typescript
import { createTeamsWarRoomThread, postAnnotationToTeams } from '../services/war-room';
import type { WarRoomCreatedPayload, WarRoomAnnotationPayload } from '../types';
```

**Change 3 — Add handling in the card dispatch block** (after the last existing card type case, before the final `sendProactiveCard(card)` call). Replace the generic dispatch with type-specific handling for the two new types:

Find the section of notify.ts where card dispatch happens and add:
```typescript
// War room card types use their own dispatch functions (Phase 53)
if (body.card_type === 'war_room_created') {
  const result = await createTeamsWarRoomThread(body.payload as WarRoomCreatedPayload);
  const response: NotifyResponse = result.ok
    ? { ok: true, message_id: result.messageId }
    : { ok: false, error: result.error };
  res.status(result.ok ? 200 : 503).json(response);
  return;
}

if (body.card_type === 'war_room_annotation') {
  const result = await postAnnotationToTeams(body.payload as WarRoomAnnotationPayload);
  const response: NotifyResponse = result.ok
    ? { ok: true, message_id: result.messageId }
    : { ok: false, error: 'Failed to post annotation card' };
  res.status(result.ok ? 200 : 503).json(response);
  return;
}
```

These two early-return branches must be inserted **before** the generic card dispatch block (`let card: Record<string, unknown>;` etc.) so they are reached first for these card types.
</action>

<acceptance_criteria>
- `grep '"war_room_created"' services/teams-bot/src/routes/notify.ts` exits 0
- `grep '"war_room_annotation"' services/teams-bot/src/routes/notify.ts` exits 0
- `grep "createTeamsWarRoomThread" services/teams-bot/src/routes/notify.ts` exits 0
- `grep "postAnnotationToTeams" services/teams-bot/src/routes/notify.ts` exits 0
- `grep "WarRoomCreatedPayload" services/teams-bot/src/routes/notify.ts` exits 0
- `grep -c '"war_room' services/teams-bot/src/routes/notify.ts` outputs `2` (one for each new type in VALID_CARD_TYPES — they appear again in the if-branches so total may be >2; use: `grep '"war_room_created"' services/teams-bot/src/routes/notify.ts | wc -l` ≥ 2)
</acceptance_criteria>

---

### Task 5: Create `services/teams-bot/src/__tests__/war-room.test.ts`

<read_first>
- `services/teams-bot/src/__tests__/` directory listing — existing test file naming patterns; check if `vitest` or `jest` is used
- `services/teams-bot/src/services/war-room.ts` (just written) — exact function signatures and return shapes to test
- `services/teams-bot/src/cards/war-room-card.ts` (just written) — exact card builder output to test
- `services/teams-bot/package.json` — confirm test framework (`vitest` is used per Phase 52 pattern)
</read_first>

<action>
Create `services/teams-bot/src/__tests__/war-room.test.ts` with ≥20 tests across 4 test classes.

**Imports:**
```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  registerWarRoomThread,
  lookupWarRoomThread,
  _resetRegistry,
  syncTeamsMessageToWarRoom,
} from '../services/war-room';
import { buildWarRoomCreatedCard, buildWarRoomAnnotationCard } from '../cards/war-room-card';
import type { WarRoomCreatedPayload, WarRoomAnnotationPayload } from '../types';
```

**`describe('WarRoomThreadRegistry')`** (5 tests):
- `registers and looks up a thread` — `registerWarRoomThread('msg-001', 'inc-001')`; `expect(lookupWarRoomThread('msg-001')).toBe('inc-001')`
- `returns undefined for unknown message id` — `expect(lookupWarRoomThread('unknown')).toBeUndefined()`
- `overwrites existing registration` — register `msg-001` → `inc-001`, then re-register `msg-001` → `inc-002`; assert lookup returns `inc-002`
- `_resetRegistry clears all entries` — register two entries; call `_resetRegistry()`; assert both return `undefined`
- `registers multiple threads independently` — register 3 threads; assert all 3 look up correctly

**`describe('buildWarRoomCreatedCard')`** (6 tests):
- `returns valid Adaptive Card schema` — call with full payload; assert `card.type === 'AdaptiveCard'`, `card.version === '1.5'`, `card.$schema` contains `adaptivecards.io`
- `includes incident_id in fact set` — assert `JSON.stringify(card)` contains `payload.incident_id`
- `includes participant names in fact set` — payload with 2 participants; assert both names in `JSON.stringify(card)`
- `includes Open War Room action` — assert `JSON.stringify(card)` contains `'war_room=1'`
- `includes Open Incident action when incident_url provided` — payload with `incident_url='https://aap.example.com/incidents/inc-001'`; assert card actions include this URL
- `handles missing optional fields gracefully` — payload with only `incident_id`, `severity`, empty `participants`; assert card renders without error (no exception thrown)

**`describe('buildWarRoomAnnotationCard')`** (5 tests):
- `returns valid Adaptive Card schema` — assert `card.type === 'AdaptiveCard'`, `card.version === '1.5'`
- `includes annotation content` — assert `JSON.stringify(card)` contains annotation content
- `includes author display_name` — assert `JSON.stringify(card)` contains `display_name`
- `includes trace_event_id when set` — payload with `trace_event_id='trace-abc'`; assert `'trace-abc'` in `JSON.stringify(card)`
- `omits trace_event_id block when null` — `trace_event_id: null`; assert `'Pinned to trace event'` NOT in `JSON.stringify(card)`

**`describe('syncTeamsMessageToWarRoom')`** (6 tests):
Using `vi.stubGlobal('fetch', ...)` to mock global fetch:
- `returns ok:false when GATEWAY_INTERNAL_URL not set` — ensure env var is empty; assert `result.ok === false`, `result.error` contains `'GATEWAY_INTERNAL_URL'`
- `returns ok:true on successful gateway POST` — stub fetch to return `{ ok: true, json: async () => ({ annotation: { id: 'ann-001' } }) }`; call with valid `incidentId`; assert `result.ok === true`, `result.annotationId === 'ann-001'`
- `truncates content to 4096 chars` — capture the `body` passed to fetch; call with `content = 'x'.repeat(5000)`; assert parsed body `content.length === 4096`
- `returns ok:false on gateway error status` — stub fetch returns `{ ok: false, status: 503, json: async () => ({ error: 'unavailable' }) }`; assert `result.ok === false`, `result.error` contains `'503'` or `'unavailable'`
- `returns ok:false on network error` — stub fetch throws `new Error('ECONNREFUSED')`; assert `result.ok === false`, `result.error` contains `'ECONNREFUSED'`
- `uses correct endpoint path` — capture `url` arg to fetch; call with `incidentId='inc-123'`; assert URL contains `/api/v1/incidents/inc-123/war-room/annotations`

Use `beforeEach(() => { _resetRegistry(); vi.clearAllMocks(); })` in each describe block.
</action>

<acceptance_criteria>
- File `services/teams-bot/src/__tests__/war-room.test.ts` exists
- `grep -c "it(" services/teams-bot/src/__tests__/war-room.test.ts` outputs a number >= 20
- `grep "describe.*WarRoomThreadRegistry" services/teams-bot/src/__tests__/war-room.test.ts` exits 0
- `grep "describe.*buildWarRoomCreatedCard" services/teams-bot/src/__tests__/war-room.test.ts` exits 0
- `grep "describe.*buildWarRoomAnnotationCard" services/teams-bot/src/__tests__/war-room.test.ts` exits 0
- `grep "describe.*syncTeamsMessageToWarRoom" services/teams-bot/src/__tests__/war-room.test.ts` exits 0
- `grep "slice(0, 4096)\|4096 chars\|truncates content" services/teams-bot/src/__tests__/war-room.test.ts` exits 0
- `grep "_resetRegistry" services/teams-bot/src/__tests__/war-room.test.ts` exits 0
- `cd services/teams-bot && npx vitest run src/__tests__/war-room.test.ts` exits 0 with all tests passing
</acceptance_criteria>

---

## Verification

```bash
# 1. TypeScript compile — no errors in teams-bot
cd services/teams-bot && npx tsc --noEmit 2>&1 | head -20

# 2. All new files exist
for f in \
  "services/teams-bot/src/cards/war-room-card.ts" \
  "services/teams-bot/src/services/war-room.ts" \
  "services/teams-bot/src/__tests__/war-room.test.ts"; do
  test -f "$f" && echo "OK: $f" || echo "MISSING: $f"
done

# 3. VALID_CARD_TYPES now includes both war room types
grep '"war_room_created"' services/teams-bot/src/routes/notify.ts
grep '"war_room_annotation"' services/teams-bot/src/routes/notify.ts

# 4. Types added to types.ts
grep "WarRoomCreatedPayload" services/teams-bot/src/types.ts
grep "WarRoomAnnotationPayload" services/teams-bot/src/types.ts

# 5. All unit tests pass
cd services/teams-bot && npx vitest run src/__tests__/war-room.test.ts

# 6. Full bot test suite still passes (no regressions)
cd services/teams-bot && npx vitest run
```

## must_haves

- [ ] `services/teams-bot/src/types.ts` exports `WarRoomCreatedPayload` and `WarRoomAnnotationPayload`
- [ ] `services/teams-bot/src/cards/war-room-card.ts` exports `buildWarRoomCreatedCard` and `buildWarRoomAnnotationCard`; both return Adaptive Card v1.5 with `$schema` and `version: "1.5"`
- [ ] `services/teams-bot/src/services/war-room.ts` exports `createTeamsWarRoomThread`, `syncTeamsMessageToWarRoom`, `postAnnotationToTeams`, `registerWarRoomThread`, `lookupWarRoomThread`, `_resetRegistry`
- [ ] `syncTeamsMessageToWarRoom` enforces `.slice(0, 4096)` content truncation before gateway POST
- [ ] `routes/notify.ts` `VALID_CARD_TYPES` includes `"war_room_created"` and `"war_room_annotation"`
- [ ] `routes/notify.ts` handles both new card types with early-return dispatch before the generic card block
- [ ] `services/teams-bot/src/__tests__/war-room.test.ts` has ≥20 tests all passing
- [ ] `npx tsc --noEmit` exits 0 in `services/teams-bot/`
- [ ] No regressions in existing Teams bot test suite
