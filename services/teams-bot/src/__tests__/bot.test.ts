import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock dependencies before importing
vi.mock("../services/gateway-client", () => ({
  GatewayClient: vi.fn(),
}));

vi.mock("../services/conversation-state", () => ({
  getThreadId: vi.fn(),
  setThreadId: vi.fn(),
}));

vi.mock("../services/proactive", () => ({
  setConversationReference: vi.fn(),
}));

import { AapTeamsBot } from "../bot";

// Helper to create a mock TurnContext
function createMockContext(overrides: Record<string, unknown> = {}) {
  const sentActivities: unknown[] = [];
  return {
    activity: {
      text: "Hello",
      type: "message",
      from: { id: "user-1", name: "operator@contoso.com" },
      conversation: { id: "conv-123" },
      value: undefined,
      ...overrides,
    },
    sendActivity: vi.fn().mockImplementation((activity: unknown) => {
      sentActivities.push(activity);
      return Promise.resolve({ id: "msg-1" });
    }),
    sentActivities,
  };
}

// Helper to create a mock GatewayClient
function createMockGateway() {
  return {
    chat: vi.fn().mockResolvedValue({ thread_id: "thread-001", status: "created" }),
    getIncident: vi.fn().mockResolvedValue({ incident_id: "INC-123", thread_id: "thread-inc" }),
    approveProposal: vi.fn().mockResolvedValue(undefined),
    rejectProposal: vi.fn().mockResolvedValue(undefined),
    listPendingApprovals: vi.fn().mockResolvedValue([]),
  };
}

describe("AapTeamsBot", () => {
  let bot: AapTeamsBot;
  let gateway: ReturnType<typeof createMockGateway>;

  beforeEach(() => {
    vi.clearAllMocks();
    gateway = createMockGateway();
    bot = new AapTeamsBot(gateway as any);
  });

  describe("handleMessage", () => {
    it("sends typing indicator and calls gateway.chat()", async () => {
      const ctx = createMockContext({ text: "What's wrong with vm-prod-01?" });

      await bot.handleMessage(ctx as any);

      // Typing indicator sent
      expect(ctx.sendActivity).toHaveBeenCalledWith({ type: "typing" });
      // Gateway chat called
      expect(gateway.chat).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "What's wrong with vm-prod-01?",
          user_id: "operator@contoso.com",
        }),
      );
    });

    it("parses /investigate INC-123 and calls gateway.getIncident()", async () => {
      const ctx = createMockContext({ text: "/investigate INC-123" });

      await bot.handleMessage(ctx as any);

      expect(gateway.getIncident).toHaveBeenCalledWith("INC-123");
      expect(gateway.chat).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Investigate incident INC-123",
          incident_id: "INC-123",
          thread_id: "thread-inc",
        }),
      );
    });

    it("does nothing for empty text", async () => {
      const ctx = createMockContext({ text: "   " });

      await bot.handleMessage(ctx as any);

      expect(gateway.chat).not.toHaveBeenCalled();
    });

    it("posts timeout message after MAX_TIMEOUT_MS", async () => {
      // Mock gateway.chat to never resolve
      gateway.chat.mockImplementation(
        () => new Promise<never>(() => {}), // never resolves
      );

      vi.useFakeTimers();
      const ctx = createMockContext({ text: "slow query" });

      const messagePromise = bot.handleMessage(ctx as any);
      // Advance past 120s timeout
      await vi.advanceTimersByTimeAsync(120_001);
      await messagePromise;

      // Should have sent typing + timeout message
      const calls = ctx.sendActivity.mock.calls.map((c: any) => c[0]);
      const timeoutMsg = calls.find(
        (c: any) =>
          typeof c === "string" &&
          c.includes("investigation is taking longer than expected"),
      );
      expect(timeoutMsg).toBeDefined();

      vi.useRealTimers();
    });
  });

  describe("onAdaptiveCardInvoke", () => {
    it("with verb 'approve' calls gateway.approveProposal() and returns updated card", async () => {
      const ctx = createMockContext({
        type: "invoke",
        value: {
          action: {
            verb: "approve",
            data: { approval_id: "appr-1", thread_id: "thread-1" },
          },
        },
      });

      // Access protected method via type assertion
      const result = await (bot as any).onAdaptiveCardInvoke(ctx as any);

      expect(gateway.approveProposal).toHaveBeenCalledWith(
        "appr-1",
        "thread-1",
        "operator@contoso.com",
      );
      expect(result.statusCode).toBe(200);
      expect(result.type).toBe("application/vnd.microsoft.card.adaptive");
    });

    it("with verb 'reject' calls gateway.rejectProposal() and returns updated card", async () => {
      const ctx = createMockContext({
        type: "invoke",
        value: {
          action: {
            verb: "reject",
            data: { approval_id: "appr-2", thread_id: "thread-2" },
          },
        },
      });

      const result = await (bot as any).onAdaptiveCardInvoke(ctx as any);

      expect(gateway.rejectProposal).toHaveBeenCalledWith(
        "appr-2",
        "thread-2",
        "operator@contoso.com",
      );
      expect(result.statusCode).toBe(200);
    });

    it("returns 400 when data is missing", async () => {
      const ctx = createMockContext({
        type: "invoke",
        value: {
          action: { verb: "approve", data: {} },
        },
      });

      const result = await (bot as any).onAdaptiveCardInvoke(ctx as any);

      expect(result.statusCode).toBe(400);
    });

    it("returns 400 when verb is unknown", async () => {
      const ctx = createMockContext({
        type: "invoke",
        value: {
          action: {
            verb: "unknown",
            data: { approval_id: "appr-1", thread_id: "t-1" },
          },
        },
      });

      const result = await (bot as any).onAdaptiveCardInvoke(ctx as any);

      expect(result.statusCode).toBe(400);
    });

    it("returns 500 on gateway error", async () => {
      gateway.approveProposal.mockRejectedValue(new Error("Gateway down"));
      const ctx = createMockContext({
        type: "invoke",
        value: {
          action: {
            verb: "approve",
            data: { approval_id: "appr-1", thread_id: "t-1" },
          },
        },
      });

      const result = await (bot as any).onAdaptiveCardInvoke(ctx as any);

      expect(result.statusCode).toBe(500);
    });
  });

  describe("handleInstallationUpdate", () => {
    it("calls setConversationReference", async () => {
      const { setConversationReference } = await import(
        "../services/proactive"
      );
      const ctx = createMockContext();

      // Mock TurnContext.getConversationReference
      const { TurnContext } = await import("botbuilder");
      vi.spyOn(TurnContext, "getConversationReference").mockReturnValue({
        conversation: { id: "conv-123" },
      } as any);

      // Access private method via type assertion
      await (bot as any).handleInstallationUpdate(ctx as any);

      expect(setConversationReference).toHaveBeenCalledWith(
        expect.objectContaining({
          conversation: { id: "conv-123" },
        }),
      );
    });
  });
});
