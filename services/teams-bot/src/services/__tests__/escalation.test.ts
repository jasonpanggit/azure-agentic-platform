import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { AppConfig } from "../../config";
import type { ApprovalRecord } from "../gateway-client";

// Mock the proactive module
vi.mock("../proactive", () => ({
  sendProactiveCard: vi.fn().mockResolvedValue({ ok: true, messageId: "msg-1" }),
  hasConversationReference: vi.fn().mockReturnValue(true),
}));

// Mock the reminder-card builder
vi.mock("../../cards/reminder-card", () => ({
  buildReminderCard: vi.fn().mockReturnValue({ type: "AdaptiveCard", body: [] }),
}));

import {
  checkAndEscalate,
  startEscalationScheduler,
  _resetEscalation,
  _getLastReminderTime,
  type EscalationDeps,
} from "../escalation";
import { sendProactiveCard, hasConversationReference } from "../proactive";
import { buildReminderCard } from "../../cards/reminder-card";

const mockSendProactiveCard = sendProactiveCard as ReturnType<typeof vi.fn>;
const mockHasConversationReference = hasConversationReference as ReturnType<typeof vi.fn>;
const mockBuildReminderCard = buildReminderCard as ReturnType<typeof vi.fn>;

function createMockConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    botId: "test-bot-id",
    botPassword: "",
    apiGatewayInternalUrl: "http://gateway.internal",
    webUiPublicUrl: "https://app.example.com",
    apiGatewayPublicUrl: "",
    teamsChannelId: "channel-1",
    escalationIntervalMinutes: 15,
    port: 3978,
    ...overrides,
  };
}

function createMockApproval(overrides: Partial<ApprovalRecord> = {}): ApprovalRecord {
  const now = Date.now();
  return {
    id: "appr-001",
    action_id: "act-001",
    thread_id: "thread-001",
    agent_name: "compute",
    status: "pending",
    risk_level: "high",
    proposed_at: new Date(now - 20 * 60 * 1000).toISOString(), // 20 min ago
    expires_at: new Date(now + 30 * 60 * 1000).toISOString(), // 30 min from now
    proposal: {
      description: "Restart VM vm-prod-01",
      target_resources: ["vm-prod-01"],
    },
    ...overrides,
  };
}

function createMockDeps(overrides: Partial<EscalationDeps> = {}): EscalationDeps {
  return {
    gateway: {
      listPendingApprovals: vi.fn().mockResolvedValue([]),
      chat: vi.fn(),
      getIncident: vi.fn(),
      approveProposal: vi.fn(),
      rejectProposal: vi.fn(),
    } as unknown as EscalationDeps["gateway"],
    config: createMockConfig(),
    ...overrides,
  };
}

describe("escalation scheduler", () => {
  beforeEach(() => {
    _resetEscalation();
    mockSendProactiveCard.mockClear();
    mockHasConversationReference.mockClear();
    mockBuildReminderCard.mockClear();
    mockHasConversationReference.mockReturnValue(true);
    mockSendProactiveCard.mockResolvedValue({ ok: true, messageId: "msg-1" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("checkAndEscalate skips when no ConversationReference", async () => {
    mockHasConversationReference.mockReturnValue(false);
    const deps = createMockDeps();

    const result = await checkAndEscalate(deps);

    expect(result).toBe(0);
    expect(mockSendProactiveCard).not.toHaveBeenCalled();
    expect(deps.gateway.listPendingApprovals).not.toHaveBeenCalled();
  });

  it("checkAndEscalate posts reminder for approval older than threshold", async () => {
    const approval = createMockApproval(); // 20 min ago, threshold is 15 min
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockResolvedValue([approval]);

    const result = await checkAndEscalate(deps);

    expect(result).toBe(1);
    expect(mockBuildReminderCard).toHaveBeenCalledOnce();
    expect(mockSendProactiveCard).toHaveBeenCalledOnce();
    expect(_getLastReminderTime("appr-001")).toBeDefined();
  });

  it("checkAndEscalate skips approval younger than threshold", async () => {
    const now = Date.now();
    const approval = createMockApproval({
      proposed_at: new Date(now - 5 * 60 * 1000).toISOString(), // 5 min ago (below 15 min threshold)
    });
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockResolvedValue([approval]);

    const result = await checkAndEscalate(deps);

    expect(result).toBe(0);
    expect(mockSendProactiveCard).not.toHaveBeenCalled();
  });

  it("checkAndEscalate skips expired approval", async () => {
    const now = Date.now();
    const approval = createMockApproval({
      proposed_at: new Date(now - 60 * 60 * 1000).toISOString(), // 60 min ago
      expires_at: new Date(now - 5 * 60 * 1000).toISOString(), // expired 5 min ago
    });
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockResolvedValue([approval]);

    const result = await checkAndEscalate(deps);

    expect(result).toBe(0);
    expect(mockSendProactiveCard).not.toHaveBeenCalled();
  });

  it("checkAndEscalate dedup prevents duplicate reminder in same interval", async () => {
    const approval = createMockApproval(); // 20 min ago
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockResolvedValue([approval]);

    // First call — should post
    const result1 = await checkAndEscalate(deps);
    expect(result1).toBe(1);
    expect(mockSendProactiveCard).toHaveBeenCalledOnce();

    // Second call — should skip (dedup)
    const result2 = await checkAndEscalate(deps);
    expect(result2).toBe(0);
    expect(mockSendProactiveCard).toHaveBeenCalledOnce(); // Still only once
  });

  it("checkAndEscalate handles gateway error gracefully", async () => {
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Network failure"),
    );

    const result = await checkAndEscalate(deps);

    expect(result).toBe(0);
    // Should not crash — error is caught and logged
  });

  it("_resetEscalation clears dedup map and allows re-send", async () => {
    const approval = createMockApproval();
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockResolvedValue([approval]);

    // First call — should post
    await checkAndEscalate(deps);
    expect(mockSendProactiveCard).toHaveBeenCalledOnce();

    // Reset dedup
    _resetEscalation();

    // After reset — should post again
    const result = await checkAndEscalate(deps);
    expect(result).toBe(1);
    expect(mockSendProactiveCard).toHaveBeenCalledTimes(2);
  });

  it("startEscalationScheduler returns interval ID that can be cleared", () => {
    const deps = createMockDeps();

    const intervalId = startEscalationScheduler(deps);

    expect(intervalId).toBeDefined();
    // Verify it's a valid interval by clearing it without error
    clearInterval(intervalId);
  });

  it("checkAndEscalate processes multiple approvals and skips/posts correctly", async () => {
    const now = Date.now();
    const approvals = [
      createMockApproval({ id: "appr-old", proposed_at: new Date(now - 20 * 60 * 1000).toISOString() }),
      createMockApproval({ id: "appr-young", proposed_at: new Date(now - 5 * 60 * 1000).toISOString() }),
      createMockApproval({
        id: "appr-expired",
        proposed_at: new Date(now - 60 * 60 * 1000).toISOString(),
        expires_at: new Date(now - 1 * 60 * 1000).toISOString(),
      }),
    ];
    const deps = createMockDeps();
    (deps.gateway.listPendingApprovals as ReturnType<typeof vi.fn>).mockResolvedValue(approvals);

    const result = await checkAndEscalate(deps);

    // Only appr-old should be escalated (appr-young too new, appr-expired past expiry)
    expect(result).toBe(1);
    expect(mockSendProactiveCard).toHaveBeenCalledOnce();
    expect(_getLastReminderTime("appr-old")).toBeDefined();
    expect(_getLastReminderTime("appr-young")).toBeUndefined();
    expect(_getLastReminderTime("appr-expired")).toBeUndefined();
  });
});
