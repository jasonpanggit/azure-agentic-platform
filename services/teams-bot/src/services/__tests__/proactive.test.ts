import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ConversationReference, CloudAdapter, TurnContext } from "botbuilder";

// We need to test the proactive module without actually importing botbuilder internals.
// Import the module under test — it uses botbuilder types but we control the adapter.
import {
  sendProactiveCard,
  hasConversationReference,
  setConversationReference,
  initializeProactive,
  _resetProactive,
} from "../proactive";

function createMockConversationReference(): Partial<ConversationReference> {
  return {
    conversation: { id: "conv-123", isGroup: true, conversationType: "channel", tenantId: "tenant-1", name: "General" },
    bot: { id: "bot-1", name: "AAPBot" },
    serviceUrl: "https://smba.trafficmanager.net/teams/",
    channelId: "msteams",
  };
}

describe("proactive messaging", () => {
  beforeEach(() => {
    _resetProactive();
  });

  it("hasConversationReference returns false initially", () => {
    expect(hasConversationReference()).toBe(false);
  });

  it("setConversationReference + hasConversationReference returns true", () => {
    setConversationReference(createMockConversationReference());
    expect(hasConversationReference()).toBe(true);
  });

  it("sendProactiveCard returns ok:false when no ConversationReference", async () => {
    // Don't set a ConversationReference
    const result = await sendProactiveCard({ type: "AdaptiveCard" });
    expect(result.ok).toBe(false);
    expect(result.messageId).toBeUndefined();
  });

  it("sendProactiveCard returns ok:false when adapter not initialized", async () => {
    // Set reference but don't initialize adapter
    setConversationReference(createMockConversationReference());
    const result = await sendProactiveCard({ type: "AdaptiveCard" });
    expect(result.ok).toBe(false);
  });

  it("_resetProactive clears all state", () => {
    setConversationReference(createMockConversationReference());
    expect(hasConversationReference()).toBe(true);

    _resetProactive();
    expect(hasConversationReference()).toBe(false);
  });

  it("sendProactiveCard calls continueConversationAsync when properly initialized", async () => {
    const mockContinueConversation = vi.fn().mockImplementation(
      async (_appId: string, _ref: ConversationReference, callback: (ctx: TurnContext) => Promise<void>) => {
        // Simulate the turn context callback
        const mockContext = {
          sendActivity: vi.fn().mockResolvedValue({ id: "msg-abc123" }),
        } as unknown as TurnContext;
        await callback(mockContext);
      },
    );

    const mockAdapter = {
      continueConversationAsync: mockContinueConversation,
    } as unknown as CloudAdapter;

    // Initialize proactive with mock adapter
    initializeProactive(mockAdapter, "test-bot-id");
    setConversationReference(createMockConversationReference());

    const card = { type: "AdaptiveCard", body: [] };
    const result = await sendProactiveCard(card);

    expect(result.ok).toBe(true);
    expect(result.messageId).toBe("msg-abc123");
    expect(mockContinueConversation).toHaveBeenCalledOnce();
    expect(mockContinueConversation).toHaveBeenCalledWith(
      "test-bot-id",
      expect.objectContaining({
        conversation: expect.objectContaining({ id: "conv-123" }),
      }),
      expect.any(Function),
    );
  });

  it("sendProactiveCard returns ok:false on continueConversationAsync error", async () => {
    const mockAdapter = {
      continueConversationAsync: vi.fn().mockRejectedValue(new Error("Teams API unavailable")),
    } as unknown as CloudAdapter;

    initializeProactive(mockAdapter, "test-bot-id");
    setConversationReference(createMockConversationReference());

    const result = await sendProactiveCard({ type: "AdaptiveCard" });

    expect(result.ok).toBe(false);
    expect(result.messageId).toBeUndefined();
  });
});
