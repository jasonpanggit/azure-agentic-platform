import type { GatewayClient } from "./gateway-client";
import { buildReminderCard } from "../cards/reminder-card";
import { sendProactiveCard, hasConversationReference } from "./proactive";
import type { AppConfig } from "../config";

const POLL_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes (D-16)

// In-memory dedup: tracks last reminder timestamp per approval_id
const lastReminderMap = new Map<string, number>();

export interface EscalationDeps {
  gateway: GatewayClient;
  config: AppConfig;
}

export function startEscalationScheduler(
  deps: EscalationDeps,
): NodeJS.Timeout {
  console.log(
    `[escalation] Starting scheduler: poll every ${POLL_INTERVAL_MS / 1000}s, ` +
      `escalation threshold ${deps.config.escalationIntervalMinutes} minutes`,
  );

  const intervalId = setInterval(async () => {
    await checkAndEscalate(deps);
  }, POLL_INTERVAL_MS);

  return intervalId;
}

export async function checkAndEscalate(
  deps: EscalationDeps,
): Promise<number> {
  // Guard: don't post if no ConversationReference (bot not installed yet)
  if (!hasConversationReference()) {
    console.log(
      "[escalation] No ConversationReference available; skipping check",
    );
    return 0;
  }

  let escalated = 0;

  try {
    const pendingApprovals = await deps.gateway.listPendingApprovals();

    const now = Date.now();
    const thresholdMs = deps.config.escalationIntervalMinutes * 60 * 1000;

    for (const approval of pendingApprovals) {
      const proposedAt = new Date(approval.proposed_at).getTime();
      const ageMs = now - proposedAt;

      // Only escalate if older than threshold
      if (ageMs < thresholdMs) {
        continue;
      }

      // Skip if already expired
      const expiresAt = new Date(approval.expires_at).getTime();
      if (now > expiresAt) {
        continue;
      }

      // Dedup: skip if reminder was already posted in this escalation interval
      const lastReminder = lastReminderMap.get(approval.id);
      if (lastReminder && now - lastReminder < thresholdMs) {
        continue;
      }

      // Build and post reminder card
      const reminderPayload = {
        approval_id: approval.id,
        thread_id: approval.thread_id,
        original_action_description:
          ((approval.proposal as Record<string, unknown>)
            ?.description as string) ?? "Unknown action",
        target_resources:
          ((approval.proposal as Record<string, unknown>)
            ?.target_resources as string[]) ?? [],
        risk_level: approval.risk_level as "critical" | "high",
        created_at: approval.proposed_at,
        expires_at: approval.expires_at,
      };

      const card = buildReminderCard(reminderPayload, deps.config.webUiPublicUrl);
      const result = await sendProactiveCard(card);

      if (result.ok) {
        lastReminderMap.set(approval.id, now);
        escalated++;
        console.log(
          `[escalation] Posted reminder for approval ${approval.id}`,
        );
      }
    }
  } catch (error) {
    // Non-fatal: log and retry on next interval (Section 7: error handling)
    console.error("[escalation] Error checking pending approvals:", error);
  }

  return escalated;
}

// Clean up stale dedup entries (approvals no longer pending)
export function cleanupDedupMap(activeApprovalIds: Set<string>): number {
  let cleaned = 0;
  for (const key of lastReminderMap.keys()) {
    if (!activeApprovalIds.has(key)) {
      lastReminderMap.delete(key);
      cleaned++;
    }
  }
  return cleaned;
}

// For testing
export function _resetEscalation(): void {
  lastReminderMap.clear();
}

export function _getLastReminderTime(
  approvalId: string,
): number | undefined {
  return lastReminderMap.get(approvalId);
}
