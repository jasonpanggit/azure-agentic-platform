/**
 * In-memory conversation state for tracking Foundry thread_id per Teams conversation.
 *
 * Per D-13: free-form messages without an incident_id get a new Foundry thread.
 * Follow-up messages in the same Teams conversation reuse that thread_id.
 *
 * This is in-memory only — lost on restart. Acceptable for Phase 6 MVP.
 * The thread_id can be re-derived from incident records if needed.
 */

interface ConversationThread {
  threadId: string;
  incidentId?: string;
  lastUsed: number;
}

const conversationMap = new Map<string, ConversationThread>();

/** TTL: 24 hours — conversations older than this are evicted */
const TTL_MS = 24 * 60 * 60 * 1000;

/**
 * Get the Foundry thread_id for a Teams conversation.
 * Returns undefined if no thread exists or the entry has expired.
 * Refreshes the lastUsed timestamp on successful access.
 */
export function getThreadId(teamsConversationId: string): string | undefined {
  const entry = conversationMap.get(teamsConversationId);
  if (!entry) return undefined;
  if (Date.now() - entry.lastUsed > TTL_MS) {
    conversationMap.delete(teamsConversationId);
    return undefined;
  }
  entry.lastUsed = Date.now();
  return entry.threadId;
}

/**
 * Store a Foundry thread_id mapped to a Teams conversation.
 */
export function setThreadId(
  teamsConversationId: string,
  threadId: string,
  incidentId?: string,
): void {
  conversationMap.set(teamsConversationId, {
    threadId,
    incidentId,
    lastUsed: Date.now(),
  });
}

/**
 * Remove entries older than the TTL. Returns the count of cleared entries.
 */
export function clearExpired(): number {
  const now = Date.now();
  let cleared = 0;
  for (const [key, value] of conversationMap.entries()) {
    if (now - value.lastUsed > TTL_MS) {
      conversationMap.delete(key);
      cleared++;
    }
  }
  return cleared;
}

/** For testing — clears all state. */
export function _resetState(): void {
  conversationMap.clear();
}
