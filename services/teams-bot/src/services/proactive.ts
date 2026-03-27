import {
  type ConversationReference,
  TurnContext,
  type CloudAdapter,
  CardFactory,
} from "botbuilder";

let savedConversationReference: Partial<ConversationReference> | null = null;
let botAdapter: CloudAdapter | null = null;
let botAppId: string = "";

/**
 * Initialize the proactive messaging module with the Bot Framework adapter.
 * Called once from index.ts during server startup.
 */
export function initializeProactive(adapter: CloudAdapter, appId: string): void {
  botAdapter = adapter;
  botAppId = appId;
}

/**
 * Store a ConversationReference for later proactive messaging.
 * Called from AapTeamsBot.onInstallationUpdate when the bot is installed in a team/channel.
 */
export function setConversationReference(
  ref: Partial<ConversationReference>,
): void {
  savedConversationReference = ref;
  console.log(
    "[proactive] ConversationReference captured for channel:",
    ref.conversation?.id,
  );
}

/**
 * Check whether a ConversationReference has been captured.
 */
export function hasConversationReference(): boolean {
  return savedConversationReference !== null;
}

/**
 * Send an Adaptive Card proactively to the configured Teams channel.
 * Uses adapter.continueConversationAsync() with the saved ConversationReference.
 */
export async function sendProactiveCard(
  card: Record<string, unknown>,
): Promise<{ ok: boolean; messageId?: string }> {
  if (!savedConversationReference) {
    console.warn(
      "[proactive] No ConversationReference available. Bot must be installed in a team first.",
    );
    return { ok: false };
  }
  if (!botAdapter) {
    console.warn(
      "[proactive] Adapter not initialized. Call initializeProactive() first.",
    );
    return { ok: false };
  }

  try {
    let messageId: string | undefined;
    await botAdapter.continueConversationAsync(
      botAppId,
      savedConversationReference as ConversationReference,
      async (turnContext: TurnContext) => {
        const response = await turnContext.sendActivity({
          attachments: [CardFactory.adaptiveCard(card)],
        });
        messageId = response?.id;
      },
    );
    return { ok: true, messageId };
  } catch (error) {
    console.error("[proactive] Failed to send card:", error);
    return { ok: false };
  }
}

/**
 * Send a plain text message proactively to the configured Teams channel.
 */
export async function sendProactiveText(
  text: string,
): Promise<{ ok: boolean; messageId?: string }> {
  if (!savedConversationReference || !botAdapter) {
    return { ok: false };
  }
  try {
    let messageId: string | undefined;
    await botAdapter.continueConversationAsync(
      botAppId,
      savedConversationReference as ConversationReference,
      async (turnContext: TurnContext) => {
        const response = await turnContext.sendActivity(text);
        messageId = response?.id;
      },
    );
    return { ok: true, messageId };
  } catch (error) {
    console.error("[proactive] Failed to send text:", error);
    return { ok: false };
  }
}

/** For testing — reset all proactive state. */
export function _resetProactive(): void {
  savedConversationReference = null;
  botAdapter = null;
  botAppId = "";
}
