import type { SopSummaryPayload } from "../types";

export function buildSopSummaryCard(
  payload: SopSummaryPayload,
): Record<string, unknown> {
  const outcomeLabel =
    payload.outcome === "resolved"
      ? "Resolved"
      : payload.outcome === "escalated"
        ? "Escalated"
        : payload.outcome === "pending_approval"
          ? "Pending Approval"
          : "Failed";

  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `SOP Execution Summary -- ${outcomeLabel}`,
        weight: "Bolder",
        size: "Medium",
      },
      {
        type: "FactSet",
        facts: [
          { title: "Incident", value: payload.incident_id },
          { title: "Resource", value: payload.resource_name },
          { title: "SOP", value: payload.sop_title },
          { title: "Steps Run", value: String(payload.steps_run) },
          { title: "Steps Skipped", value: String(payload.steps_skipped) },
          { title: "Outcome", value: payload.outcome },
        ],
      },
    ],
  };
}
