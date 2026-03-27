import { describe, it, expect } from "vitest";
import {
  buildOutcomeCard,
  getOutcomeColor,
  getOutcomeTitle,
} from "../../cards/outcome-card";
import type { OutcomePayload } from "../../types";

const basePayload: OutcomePayload = {
  incident_id: "INC-001",
  approval_id: "APR-001",
  action_description: "Restarted vm-prod-01 to resolve high CPU",
  outcome_status: "Succeeded",
  duration_seconds: 42,
  resulting_resource_state: "Running",
  approver_upn: "operator@contoso.com",
  executed_at: "2026-03-27T14:45:00Z",
};

describe("buildOutcomeCard", () => {
  it("returns a valid card with version 1.5", () => {
    const card = buildOutcomeCard(basePayload, "https://ui.example.com");
    expect(card.version).toBe("1.5");
    expect(card.type).toBe("AdaptiveCard");
  });

  it("Succeeded maps to title 'Remediation Succeeded' and color 'good'", () => {
    const card = buildOutcomeCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.text).toBe("Remediation Succeeded");
    expect(titleBlock.color).toBe("good");
  });

  it("Failed maps to title 'Remediation Failed' and color 'attention'", () => {
    const payload = { ...basePayload, outcome_status: "Failed" as const };
    const card = buildOutcomeCard(payload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.text).toBe("Remediation Failed");
    expect(titleBlock.color).toBe("attention");
  });

  it("Aborted maps to title 'Remediation Aborted' and color 'warning'", () => {
    const payload = { ...basePayload, outcome_status: "Aborted" as const };
    const card = buildOutcomeCard(payload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.text).toBe("Remediation Aborted");
    expect(titleBlock.color).toBe("warning");
  });

  it("Duration fact shows '{N}s' format", () => {
    const card = buildOutcomeCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const factSet = body[2] as Record<string, unknown>;
    const facts = factSet.facts as Array<{ title: string; value: string }>;
    const durationFact = facts.find((f) => f.title === "Duration");
    expect(durationFact?.value).toBe("42s");
  });

  it("action is Action.OpenUrl with correct URL", () => {
    const webUiUrl = "https://ui.example.com";
    const card = buildOutcomeCard(basePayload, webUiUrl);
    const actions = card.actions as Record<string, unknown>[];
    expect(actions[0].type).toBe("Action.OpenUrl");
    expect(actions[0].title).toBe("View Details in Web UI");
    expect(actions[0].url).toBe(
      `${webUiUrl}/incidents/${basePayload.incident_id}`,
    );
  });
});

describe("getOutcomeColor", () => {
  it("returns good for Succeeded", () => {
    expect(getOutcomeColor("Succeeded")).toBe("good");
  });

  it("returns attention for Failed", () => {
    expect(getOutcomeColor("Failed")).toBe("attention");
  });

  it("returns warning for Aborted", () => {
    expect(getOutcomeColor("Aborted")).toBe("warning");
  });
});

describe("getOutcomeTitle", () => {
  it("maps Succeeded to 'Remediation Succeeded'", () => {
    expect(getOutcomeTitle("Succeeded")).toBe("Remediation Succeeded");
  });

  it("maps Failed to 'Remediation Failed'", () => {
    expect(getOutcomeTitle("Failed")).toBe("Remediation Failed");
  });

  it("maps Aborted to 'Remediation Aborted'", () => {
    expect(getOutcomeTitle("Aborted")).toBe("Remediation Aborted");
  });
});
