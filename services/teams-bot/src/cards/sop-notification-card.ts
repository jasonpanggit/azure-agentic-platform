import type { SopNotificationPayload } from "../types";

export function buildSopNotificationCard(
  payload: SopNotificationPayload,
): Record<string, unknown> {
  const severityColor =
    payload.severity === "critical"
      ? "Attention"
      : payload.severity === "warning"
        ? "Warning"
        : "Good";

  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: "AIOps SOP Notification",
        weight: "Bolder",
        size: "Medium",
        color: severityColor,
      },
      {
        type: "FactSet",
        facts: [
          { title: "Incident", value: payload.incident_id },
          { title: "Resource", value: payload.resource_name },
          { title: "Severity", value: payload.severity.toUpperCase() },
          { title: "SOP Step", value: payload.sop_step },
        ],
      },
      {
        type: "TextBlock",
        text: payload.message,
        wrap: true,
      },
    ],
  };
}
