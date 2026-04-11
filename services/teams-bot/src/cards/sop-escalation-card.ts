import type { SopEscalationPayload } from "../types";

export function buildSopEscalationCard(
  payload: SopEscalationPayload,
): Record<string, unknown> {
  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `SOP Escalation -- ${payload.incident_id}`,
        weight: "Bolder",
        size: "Medium",
        color: "Attention",
      },
      {
        type: "FactSet",
        facts: [
          { title: "Resource", value: payload.resource_name },
          { title: "SOP Step", value: payload.sop_step },
          { title: "Context", value: payload.context },
        ],
      },
      { type: "TextBlock", text: payload.message, wrap: true },
    ],
    actions: [
      {
        type: "Action.Submit",
        title: "Acknowledge",
        data: {
          action: "acknowledge_escalation",
          incident_id: payload.incident_id,
        },
      },
    ],
  };
}
