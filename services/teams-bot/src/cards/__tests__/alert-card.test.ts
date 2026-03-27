import { describe, it, expect } from "vitest";
import {
  buildAlertCard,
  getSeverityColor,
} from "../../cards/alert-card";
import type { AlertPayload } from "../../types";

const basePayload: AlertPayload = {
  incident_id: "INC-001",
  alert_title: "High CPU on vm-prod-01",
  resource_name: "vm-prod-01",
  severity: "Sev1",
  subscription_name: "prod-subscription",
  domain: "compute",
  timestamp: "2026-03-27T14:30:00Z",
};

describe("buildAlertCard", () => {
  it("returns a valid card with version 1.5 and type AdaptiveCard", () => {
    const card = buildAlertCard(basePayload, "https://ui.example.com");
    expect(card.version).toBe("1.5");
    expect(card.type).toBe("AdaptiveCard");
    expect(card.$schema).toBe(
      "http://adaptivecards.io/schemas/adaptive-card.json",
    );
  });

  it("formats title as 'Alert: {alert_title}'", () => {
    const card = buildAlertCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.text).toBe("Alert: High CPU on vm-prod-01");
  });

  it("maps Sev0 to title color 'attention'", () => {
    const payload = { ...basePayload, severity: "Sev0" as const };
    const card = buildAlertCard(payload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const titleBlock = body[0] as Record<string, unknown>;
    expect(titleBlock.color).toBe("attention");
  });

  it("maps Sev1 to title color 'attention'", () => {
    const card = buildAlertCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    expect((body[0] as Record<string, unknown>).color).toBe("attention");
  });

  it("maps Sev2 to title color 'warning'", () => {
    const payload = { ...basePayload, severity: "Sev2" as const };
    const card = buildAlertCard(payload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    expect((body[0] as Record<string, unknown>).color).toBe("warning");
  });

  it("maps Sev3 to title color 'default'", () => {
    const payload = { ...basePayload, severity: "Sev3" as const };
    const card = buildAlertCard(payload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    expect((body[0] as Record<string, unknown>).color).toBe("default");
  });

  it("action is Action.OpenUrl with correct URL pattern", () => {
    const webUiUrl = "https://ui.example.com";
    const card = buildAlertCard(basePayload, webUiUrl);
    const actions = card.actions as Record<string, unknown>[];
    expect(actions[0].type).toBe("Action.OpenUrl");
    expect(actions[0].title).toBe("Investigate in Web UI");
    expect(actions[0].url).toBe(
      `${webUiUrl}/incidents/${basePayload.incident_id}`,
    );
  });

  it("FactSet contains 5 facts: Resource, Severity, Subscription, Time, Domain", () => {
    const card = buildAlertCard(basePayload, "https://ui.example.com");
    const body = card.body as Record<string, unknown>[];
    const factSet = body[1] as Record<string, unknown>;
    const facts = factSet.facts as Array<{ title: string; value: string }>;
    expect(facts).toHaveLength(5);
    expect(facts.map((f) => f.title)).toEqual([
      "Resource",
      "Severity",
      "Subscription",
      "Time",
      "Domain",
    ]);
  });
});

describe("getSeverityColor", () => {
  it("returns attention for Sev0", () => {
    expect(getSeverityColor("Sev0")).toBe("attention");
  });

  it("returns attention for Sev1", () => {
    expect(getSeverityColor("Sev1")).toBe("attention");
  });

  it("returns warning for Sev2", () => {
    expect(getSeverityColor("Sev2")).toBe("warning");
  });

  it("returns default for Sev3", () => {
    expect(getSeverityColor("Sev3")).toBe("default");
  });
});
