import { describe, it, expect } from "vitest";
import { buildSopNotificationCard } from "../sop-notification-card";
import { buildSopEscalationCard } from "../sop-escalation-card";
import { buildSopSummaryCard } from "../sop-summary-card";

describe("SOP notification cards", () => {
  describe("buildSopNotificationCard", () => {
    it("returns an AdaptiveCard object", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-001",
        resource_name: "vm-prod-01",
        message: "CPU threshold breached",
        severity: "warning",
        sop_step: "Step 2: Notify operator",
      });
      expect(card.type).toBe("AdaptiveCard");
    });

    it("uses version 1.5", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-001",
        resource_name: "vm1",
        message: "test",
        severity: "info",
        sop_step: "Step 1",
      });
      expect(card.version).toBe("1.5");
    });

    it("includes incident_id in the card body", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-test-001",
        resource_name: "vm1",
        message: "test",
        severity: "info",
        sop_step: "Step 1",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("inc-test-001");
    });

    it("includes resource_name in the card body", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-001",
        resource_name: "my-vm-prod",
        message: "test",
        severity: "critical",
        sop_step: "Step 2",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("my-vm-prod");
    });

    it("includes severity in the card body", () => {
      const card = buildSopNotificationCard({
        incident_id: "inc-001",
        resource_name: "vm1",
        message: "test",
        severity: "critical",
        sop_step: "Step 1",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("CRITICAL");
    });
  });

  describe("buildSopEscalationCard", () => {
    it("returns an AdaptiveCard with acknowledge action", () => {
      const card = buildSopEscalationCard({
        incident_id: "inc-002",
        resource_name: "vm2",
        message: "escalating to SRE",
        sop_step: "Step 5: Escalate",
        context: "Triage inconclusive after 3 steps",
      });
      expect(card.type).toBe("AdaptiveCard");
      const json = JSON.stringify(card);
      expect(json.toLowerCase()).toContain("acknowledge");
    });

    it("includes incident_id in the card", () => {
      const card = buildSopEscalationCard({
        incident_id: "inc-esc-99",
        resource_name: "vm2",
        message: "test",
        sop_step: "Step 5",
        context: "test context",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("inc-esc-99");
    });
  });

  describe("buildSopSummaryCard", () => {
    it("returns an AdaptiveCard with steps_run count", () => {
      const card = buildSopSummaryCard({
        incident_id: "inc-003",
        resource_name: "vm3",
        sop_title: "VM High CPU",
        steps_run: 4,
        steps_skipped: 1,
        outcome: "resolved",
      });
      expect(card.type).toBe("AdaptiveCard");
      const json = JSON.stringify(card);
      expect(json).toContain("4");
    });

    it("includes sop_title in the card", () => {
      const card = buildSopSummaryCard({
        incident_id: "inc-003",
        resource_name: "vm3",
        sop_title: "VM High CPU Triage",
        steps_run: 3,
        steps_skipped: 0,
        outcome: "resolved",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("VM High CPU Triage");
    });

    it("includes outcome in the card", () => {
      const card = buildSopSummaryCard({
        incident_id: "inc-003",
        resource_name: "vm3",
        sop_title: "Test",
        steps_run: 2,
        steps_skipped: 0,
        outcome: "escalated",
      });
      const json = JSON.stringify(card);
      expect(json).toContain("escalated");
    });
  });
});
