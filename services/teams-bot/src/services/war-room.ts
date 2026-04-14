/**
 * War Room Teams Integration Service (Phase 53)
 *
 * Handles:
 * 1. Creating a Teams war room thread (Adaptive Card in the configured channel)
 * 2. WarRoomThreadRegistry — maps Teams message IDs to incident IDs for
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
// In-memory map: teamsMessageId → incidentId
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
          content: content.slice(0, 4096),
          operator_id: operatorId,
          display_name: displayName,
          trace_event_id: null,
        }),
        signal: AbortSignal.timeout(10000),
      }
    );

    if (!res.ok) {
      const errData = await res.json().catch(() => ({})) as Record<string, unknown>;
      return { ok: false, error: (errData?.error as string | undefined) ?? `Gateway error: ${res.status}` };
    }

    const data = await res.json() as Record<string, unknown>;
    const annotation = data?.annotation as Record<string, unknown> | undefined;
    const annotationId: string = (annotation?.id as string | undefined) ?? '';
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
