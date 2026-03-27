import type { OutcomePayload } from "../types";

export function getOutcomeColor(status: string): string {
  switch (status) {
    case "Succeeded":
      return "good";
    case "Failed":
      return "attention";
    case "Aborted":
      return "warning";
    default:
      return "default";
  }
}

export function getOutcomeTitle(status: string): string {
  switch (status) {
    case "Succeeded":
      return "Remediation Succeeded";
    case "Failed":
      return "Remediation Failed";
    case "Aborted":
      return "Remediation Aborted";
    default:
      return `Remediation ${status}`;
  }
}

export function buildOutcomeCard(
  payload: OutcomePayload,
  webUiPublicUrl: string,
): Record<string, unknown> {
  const titleColor = getOutcomeColor(payload.outcome_status);
  const title = getOutcomeTitle(payload.outcome_status);

  return {
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: title,
        weight: "Bolder",
        size: "Medium",
        color: titleColor,
      },
      {
        type: "TextBlock",
        text: payload.action_description,
        wrap: true,
        spacing: "small",
      },
      {
        type: "FactSet",
        spacing: "medium",
        facts: [
          { title: "Status", value: payload.outcome_status },
          { title: "Duration", value: `${payload.duration_seconds}s` },
          { title: "Resource State", value: payload.resulting_resource_state },
          { title: "Approved By", value: payload.approver_upn },
          { title: "Executed At", value: payload.executed_at },
        ],
      },
    ],
    actions: [
      {
        type: "Action.OpenUrl",
        title: "View Details in Web UI",
        url: `${webUiPublicUrl}/incidents/${payload.incident_id}`,
      },
    ],
  };
}
