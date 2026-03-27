import type { ApprovalPayload } from "../types";

export function getRiskColor(riskLevel: string): string {
  switch (riskLevel) {
    case "critical":
      return "attention";
    case "high":
      return "warning";
    default:
      return "default";
  }
}

export function buildApprovalCard(
  payload: ApprovalPayload,
): Record<string, unknown> {
  const titleColor = getRiskColor(payload.risk_level);
  const riskLabel = payload.risk_level.toUpperCase();
  const targetCsv = payload.proposal.target_resources.join(", ");

  return {
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: `Remediation Approval Required (${riskLabel})`,
        weight: "Bolder",
        size: "Medium",
        color: titleColor,
      },
      {
        type: "TextBlock",
        text: payload.proposal.description,
        wrap: true,
        spacing: "small",
      },
      {
        type: "FactSet",
        spacing: "medium",
        facts: [
          { title: "Target", value: targetCsv },
          { title: "Impact", value: payload.proposal.estimated_impact },
          { title: "Risk Level", value: payload.risk_level },
          { title: "Reversibility", value: payload.proposal.reversibility },
          { title: "Expires", value: payload.expires_at },
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
    ],
  };
}
