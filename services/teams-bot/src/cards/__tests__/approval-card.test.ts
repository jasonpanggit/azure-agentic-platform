import { describe, it, expect } from "vitest";
import {
  buildApprovalCard,
  getRiskColor,
} from "../../cards/approval-card";
import type { ApprovalPayload } from "../../types";

const basePayload: ApprovalPayload = {
  approval_id: "APR-001",
  thread_id: "thread-abc-123",
  proposal: {
    description: "Restart vm-prod-01 to resolve high CPU condition",
    target_resources: ["vm-prod-01", "vm-prod-02"],
    estimated_impact: "30 seconds downtime",
    reversibility: "Reversible",
  },
  risk_level: "critical",
  expires_at: "2026-03-27T15:00:00Z",
};

describe("buildApprovalCard", () => {
  it("returns a valid card with version 1.5", () => {
    const card = buildApprovalCard(basePayload);
    expect(card.version).toBe("1.5");
    expect(card.type).toBe("AdaptiveCard");
  });

  it("formats title as 'Remediation Approval Required (CRITICAL)' for critical risk", () => {
    const card = buildApprovalCard(basePayload);
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.text).toBe(
      "Remediation Approval Required (CRITICAL)",
    );
  });

  it("formats title as 'Remediation Approval Required (HIGH)' for high risk", () => {
    const payload = { ...basePayload, risk_level: "high" as const };
    const card = buildApprovalCard(payload);
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.text).toBe("Remediation Approval Required (HIGH)");
  });

  it("actions use Action.Execute (NOT Action.Http)", () => {
    const card = buildApprovalCard(basePayload);
    const actions = card.actions as Record<string, unknown>[];
    for (const action of actions) {
      expect(action.type).toBe("Action.Execute");
      expect(action.type).not.toBe("Action.Http");
    }
  });

  it("Approve action has verb 'approve' and style 'positive'", () => {
    const card = buildApprovalCard(basePayload);
    const actions = card.actions as Record<string, unknown>[];
    const approveAction = actions[0];
    expect(approveAction.verb).toBe("approve");
    expect(approveAction.style).toBe("positive");
    expect(approveAction.title).toBe("Approve");
  });

  it("Reject action has verb 'reject' and style 'destructive'", () => {
    const card = buildApprovalCard(basePayload);
    const actions = card.actions as Record<string, unknown>[];
    const rejectAction = actions[1];
    expect(rejectAction.verb).toBe("reject");
    expect(rejectAction.style).toBe("destructive");
    expect(rejectAction.title).toBe("Reject");
  });

  it("action data contains approval_id and thread_id from payload", () => {
    const card = buildApprovalCard(basePayload);
    const actions = card.actions as Record<string, unknown>[];
    for (const action of actions) {
      const data = action.data as Record<string, unknown>;
      expect(data.approval_id).toBe(basePayload.approval_id);
      expect(data.thread_id).toBe(basePayload.thread_id);
    }
  });

  it("'critical' risk maps to title color 'attention'", () => {
    const card = buildApprovalCard(basePayload);
    const body = card.body as Record<string, unknown>[];
    expect((body[0] as Record<string, unknown>).color).toBe("attention");
  });

  it("'high' risk maps to title color 'warning'", () => {
    const payload = { ...basePayload, risk_level: "high" as const };
    const card = buildApprovalCard(payload);
    const body = card.body as Record<string, unknown>[];
    expect((body[0] as Record<string, unknown>).color).toBe("warning");
  });
});

describe("getRiskColor", () => {
  it("returns attention for critical", () => {
    expect(getRiskColor("critical")).toBe("attention");
  });

  it("returns warning for high", () => {
    expect(getRiskColor("high")).toBe("warning");
  });

  it("returns default for unknown", () => {
    expect(getRiskColor("unknown")).toBe("default");
  });
});
