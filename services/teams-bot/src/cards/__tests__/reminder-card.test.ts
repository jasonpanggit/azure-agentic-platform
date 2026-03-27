import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  buildReminderCard,
  computeRemainingMinutes,
} from "../../cards/reminder-card";
import type { ReminderPayload } from "../../types";

const basePayload: ReminderPayload = {
  approval_id: "APR-001",
  thread_id: "thread-abc-123",
  original_action_description: "Restart vm-prod-01 to resolve high CPU",
  target_resources: ["vm-prod-01", "vm-prod-02"],
  risk_level: "critical",
  created_at: "2026-03-27T14:00:00Z",
  expires_at: "2026-03-27T14:30:00Z",
};

describe("buildReminderCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns a valid card with version 1.5", () => {
    const card = buildReminderCard(basePayload, "https://ui.example.com");
    expect(card.version).toBe("1.5");
    expect(card.type).toBe("AdaptiveCard");
  });

  it("container has style 'warning'", () => {
    const card = buildReminderCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const container = body[0] as Record<string, unknown>;
    expect(container.type).toBe("Container");
    expect(container.style).toBe("warning");
  });

  it("header text is 'Warning: Reminder: Approval Required'", () => {
    const card = buildReminderCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const container = body[0] as Record<string, unknown>;
    const items = container.items as Record<string, unknown>[];
    expect((items[0] as Record<string, unknown>).text).toBe(
      "Warning: Reminder: Approval Required",
    );
  });

  it("when remaining <= 5 minutes, 'Expires In' fact contains '(EXPIRING SOON)'", () => {
    // Set expires_at to 3 minutes from "now"
    const now = new Date("2026-03-27T14:00:00Z");
    vi.setSystemTime(now);

    const expiresAt = new Date(now.getTime() + 3 * 60 * 1000).toISOString();
    const payload = { ...basePayload, expires_at: expiresAt };
    const card = buildReminderCard(payload, "https://ui.example.com");

    const body = card.body as Record<string, unknown>[];
    const factSet = body[2] as Record<string, unknown>;
    const facts = factSet.facts as Array<{ title: string; value: string }>;
    const expiresInFact = facts.find((f) => f.title === "Expires In");
    expect(expiresInFact?.value).toContain("EXPIRING SOON");
  });

  it("when remaining > 5 minutes, no '(EXPIRING SOON)' suffix", () => {
    const now = new Date("2026-03-27T14:00:00Z");
    vi.setSystemTime(now);

    const expiresAt = new Date(now.getTime() + 20 * 60 * 1000).toISOString();
    const payload = { ...basePayload, expires_at: expiresAt };
    const card = buildReminderCard(payload, "https://ui.example.com");

    const body = card.body as Record<string, unknown>[];
    const factSet = body[2] as Record<string, unknown>;
    const facts = factSet.facts as Array<{ title: string; value: string }>;
    const expiresInFact = facts.find((f) => f.title === "Expires In");
    expect(expiresInFact?.value).not.toContain("EXPIRING SOON");
  });

  it("actions include Action.Execute for Approve and Reject (NOT Action.Http)", () => {
    const card = buildReminderCard(basePayload, "https://ui.example.com");
    const actions = card.actions as Record<string, unknown>[];
    const executeActions = actions.filter((a) => a.type === "Action.Execute");
    expect(executeActions).toHaveLength(2);
    expect(actions.some((a) => a.type === "Action.Http")).toBe(false);

    const approveAction = executeActions.find((a) => a.verb === "approve");
    const rejectAction = executeActions.find((a) => a.verb === "reject");
    expect(approveAction).toBeDefined();
    expect(rejectAction).toBeDefined();
    expect(approveAction?.style).toBe("positive");
    expect(rejectAction?.style).toBe("destructive");
  });

  it("third action is Action.OpenUrl to '{webUiPublicUrl}/approvals/{approval_id}'", () => {
    const webUiUrl = "https://ui.example.com";
    const card = buildReminderCard(basePayload, webUiUrl);
    const actions = card.actions as Record<string, unknown>[];
    const openUrlAction = actions.find((a) => a.type === "Action.OpenUrl");
    expect(openUrlAction).toBeDefined();
    expect(openUrlAction?.title).toBe("View in Web UI");
    expect(openUrlAction?.url).toBe(
      `${webUiUrl}/approvals/${basePayload.approval_id}`,
    );
  });
});

describe("computeRemainingMinutes", () => {
  it("returns correct remaining minutes", () => {
    const now = new Date("2026-03-27T14:00:00Z");
    vi.setSystemTime(now);

    const expiresAt = new Date(now.getTime() + 10 * 60 * 1000).toISOString();
    expect(computeRemainingMinutes(expiresAt)).toBe(10);

    vi.restoreAllMocks();
  });
});
