import type { AlertPayload } from "../types";

export function getSeverityColor(severity: string): string {
  switch (severity) {
    case "Sev0":
    case "Sev1":
      return "attention";
    case "Sev2":
      return "warning";
    default:
      return "default";
  }
}

export function buildAlertCard(
  payload: AlertPayload,
  webUiPublicUrl: string,
): Record<string, unknown> {
  const titleColor = getSeverityColor(payload.severity);

  return {
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `Alert: ${payload.alert_title}`,
        weight: "Bolder",
        size: "Medium",
        color: titleColor,
      },
      {
        type: "FactSet",
        facts: [
          { title: "Resource", value: payload.resource_name },
          { title: "Severity", value: payload.severity },
          { title: "Subscription", value: payload.subscription_name },
          { title: "Time", value: payload.timestamp },
          { title: "Domain", value: payload.domain },
        ],
      },
    ],
    actions: [
      {
        type: "Action.OpenUrl",
        title: "Investigate in Web UI",
        url: `${webUiPublicUrl}/incidents/${payload.incident_id}`,
      },
    ],
  };
}
