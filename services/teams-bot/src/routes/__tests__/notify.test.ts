import { describe, it, expect, vi, beforeEach } from "vitest";
import express from "express";
import request from "supertest";
import { createNotifyRouter } from "../../routes/notify";
import type { AppConfig } from "../../config";

// Mock sendProactiveCard to avoid real Teams API calls
vi.mock("../../services/proactive", () => ({
  sendProactiveCard: vi.fn().mockResolvedValue({ ok: true, messageId: "msg-001" }),
}));

const mockConfig: AppConfig = {
  botId: "bot-123",
  botPassword: "",
  apiGatewayInternalUrl: "http://api-gateway.internal",
  webUiPublicUrl: "https://ui.example.com",
  apiGatewayPublicUrl: "",
  teamsChannelId: "channel-001",
  escalationIntervalMinutes: 15,
  port: 3978,
};

const app = express();
app.use(express.json());
app.use(createNotifyRouter(mockConfig));

const alertPayload = {
  incident_id: "INC-001",
  alert_title: "High CPU",
  resource_name: "vm-prod-01",
  severity: "Sev1",
  subscription_name: "prod-sub",
  domain: "compute",
  timestamp: "2026-03-27T14:30:00Z",
};

const approvalPayload = {
  approval_id: "APR-001",
  thread_id: "thread-abc",
  proposal: {
    description: "Restart vm-prod-01",
    target_resources: ["vm-prod-01"],
    estimated_impact: "30s downtime",
    reversibility: "Reversible",
  },
  risk_level: "critical",
  expires_at: "2026-03-27T15:00:00Z",
};

const outcomePayload = {
  incident_id: "INC-001",
  approval_id: "APR-001",
  action_description: "Restarted vm-prod-01",
  outcome_status: "Succeeded",
  duration_seconds: 30,
  resulting_resource_state: "Running",
  approver_upn: "op@contoso.com",
  executed_at: "2026-03-27T14:45:00Z",
};

const reminderPayload = {
  approval_id: "APR-001",
  thread_id: "thread-abc",
  original_action_description: "Restart vm-prod-01",
  target_resources: ["vm-prod-01"],
  risk_level: "high",
  created_at: "2026-03-27T14:00:00Z",
  expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
};

describe("POST /teams/internal/notify", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 200 with ok:true for card_type 'alert' and valid AlertPayload", async () => {
    const res = await request(app)
      .post("/teams/internal/notify")
      .send({ card_type: "alert", channel_id: "ch-001", payload: alertPayload });
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  it("returns 200 with ok:true for card_type 'approval' and valid ApprovalPayload", async () => {
    const res = await request(app)
      .post("/teams/internal/notify")
      .send({ card_type: "approval", channel_id: "ch-001", payload: approvalPayload });
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  it("returns 200 with ok:true for card_type 'outcome' and valid OutcomePayload", async () => {
    const res = await request(app)
      .post("/teams/internal/notify")
      .send({ card_type: "outcome", channel_id: "ch-001", payload: outcomePayload });
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  it("returns 200 with ok:true for card_type 'reminder' and valid ReminderPayload", async () => {
    const res = await request(app)
      .post("/teams/internal/notify")
      .send({ card_type: "reminder", channel_id: "ch-001", payload: reminderPayload });
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  it("returns 400 with ok:false for unknown card_type", async () => {
    const res = await request(app)
      .post("/teams/internal/notify")
      .send({ card_type: "unknown", channel_id: "ch-001", payload: alertPayload });
    expect(res.status).toBe(400);
    expect(res.body.ok).toBe(false);
  });

  it("returns 400 for missing payload", async () => {
    const res = await request(app)
      .post("/teams/internal/notify")
      .send({ card_type: "alert", channel_id: "ch-001" });
    expect(res.status).toBe(400);
    expect(res.body.ok).toBe(false);
  });
});
