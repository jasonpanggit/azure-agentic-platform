import type { ReminderPayload } from "../types";

export function computeRemainingMinutes(expiresAt: string): number {
  return Math.round(
    (new Date(expiresAt).getTime() - Date.now()) / 60000,
  );
}

export function buildReminderCard(
  payload: ReminderPayload,
  webUiPublicUrl: string,
): Record<string, unknown> {
  const remainingMinutes = computeRemainingMinutes(payload.expires_at);
  const expiresInValue =
    remainingMinutes <= 5
      ? `${remainingMinutes} minutes (EXPIRING SOON)`
      : `${remainingMinutes} minutes`;

  const targetCsv = payload.target_resources.join(", ");

  return {
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      {
        type: "Container",
        style: "warning",
        items: [
          {
            type: "TextBlock",
            text: "Warning: Reminder: Approval Required",
            weight: "Bolder",
            size: "Medium",
            color: "warning",
          },
        ],
      },
      {
        type: "TextBlock",
        text: payload.original_action_description,
        wrap: true,
        spacing: "small",
      },
      {
        type: "FactSet",
        spacing: "medium",
        facts: [
          { title: "Target", value: targetCsv },
          { title: "Risk Level", value: payload.risk_level },
          { title: "Pending Since", value: payload.created_at },
          { title: "Expires In", value: expiresInValue },
        ],
      },
    ],
    actions: [
      {
        type: "Action.Execute",
        title: "Approve",
        verb: "approve",
        data: {
          approval_id: payload.approval_id,
          thread_id: payload.thread_id,
        },
        style: "positive",
      },
      {
        type: "Action.Execute",
        title: "Reject",
        verb: "reject",
        data: {
          approval_id: payload.approval_id,
          thread_id: payload.thread_id,
        },
        style: "destructive",
      },
      {
        type: "Action.OpenUrl",
        title: "View in Web UI",
        url: `${webUiPublicUrl}/approvals/${payload.approval_id}`,
      },
    ],
  };
}
