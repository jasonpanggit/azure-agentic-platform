import {
  TeamsActivityHandler,
  TurnContext,
  type AdaptiveCardInvokeResponse,
} from "botbuilder";
import type { GatewayClient } from "./services/gateway-client";
import { getThreadId, setThreadId } from "./services/conversation-state";

/**
 * AapTeamsBot — the main Teams activity handler for the Azure Agentic Platform.
 *
 * Handles:
 * - Operator messages → routed to api-gateway chat endpoint
 * - /investigate <incident_id> command → incident lookup + chat
 * - Adaptive Card Action.Execute → approve/reject remediation proposals
 * - Bot installation → ConversationReference capture for proactive messaging
 */
export class AapTeamsBot extends TeamsActivityHandler {
  constructor(private readonly gateway: GatewayClient) {
    super();
  }

  /**
   * Handle text messages from operators (TEAMS-001).
   *
   * Flow: typing indicator → call gateway.chat() → 30s interim → 120s timeout
   */
  async onMessage(context: TurnContext): Promise<void> {
    const text = context.activity.text?.trim();
    if (!text) return;

    const userUpn =
      context.activity.from?.name ?? context.activity.from?.id ?? "unknown";
    const teamsConversationId = context.activity.conversation?.id ?? "";

    // Check for /investigate <incident_id> command (D-12)
    const investigateMatch = text.match(/^\/investigate\s+(\S+)/i);
    let incidentId: string | undefined;
    let threadId: string | undefined;
    let message = text;

    if (investigateMatch) {
      incidentId = investigateMatch[1];
      message = `Investigate incident ${incidentId}`;
      // Look up thread_id from incident record via api-gateway
      try {
        const incident = await this.gateway.getIncident(incidentId);
        threadId = incident.thread_id as string | undefined;
      } catch {
        // Incident not found — will create a new thread
      }
    } else {
      // Check conversation state for existing thread_id (D-13)
      threadId = getThreadId(teamsConversationId);
    }

    // Send typing indicator (D-05)
    await context.sendActivity({ type: "typing" });

    // Call api-gateway chat endpoint with timeout handling (D-05, D-06)
    const INTERIM_TIMEOUT_MS = 30_000;
    const MAX_TIMEOUT_MS = 120_000;

    let interimSent = false;
    const interimTimer = setTimeout(async () => {
      interimSent = true;
      await context.sendActivity(
        "Still working on this - complex investigation in progress...",
      );
    }, INTERIM_TIMEOUT_MS);

    try {
      const chatResponse = await Promise.race([
        this.gateway.chat({
          message,
          incident_id: incidentId,
          thread_id: threadId,
          user_id: userUpn,
        }),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("timeout")), MAX_TIMEOUT_MS),
        ),
      ]);

      clearTimeout(interimTimer);

      // Store thread_id for follow-up messages in same conversation
      setThreadId(teamsConversationId, chatResponse.thread_id, incidentId);

      // Send the response as a Teams reply
      await context.sendActivity(
        chatResponse.status === "created"
          ? `Thread created: ${chatResponse.thread_id}. Investigation started.`
          : `Response from thread ${chatResponse.thread_id}`,
      );
    } catch (error) {
      clearTimeout(interimTimer);
      const webUiUrl = process.env.WEB_UI_PUBLIC_URL ?? "";
      const incidentUrl = incidentId
        ? `${webUiUrl}/incidents/${incidentId}`
        : webUiUrl;
      await context.sendActivity(
        `The investigation is taking longer than expected. Check the Web UI for full results: ${incidentUrl}`,
      );
    }
  }

  /**
   * Handle Adaptive Card Action.Execute invokes (TEAMS-003 approval/reject).
   *
   * The approve/reject cards from 06-01 send { verb, data: { approval_id, thread_id } }.
   * This handler proxies the decision to the api-gateway and returns an updated card.
   */
  async onAdaptiveCardInvoke(
    context: TurnContext,
  ): Promise<AdaptiveCardInvokeResponse> {
    const verb = context.activity.value?.action?.verb;
    const data = context.activity.value?.action?.data;
    const userUpn =
      context.activity.from?.name ?? context.activity.from?.id ?? "unknown";

    if (!verb || !data?.approval_id || !data?.thread_id) {
      return {
        statusCode: 400,
        type: "application/vnd.microsoft.error",
        value: { code: "BadRequest", message: "Missing verb or data" },
      } as AdaptiveCardInvokeResponse;
    }

    const { approval_id, thread_id } = data;

    try {
      if (verb === "approve") {
        await this.gateway.approveProposal(approval_id, thread_id, userUpn);
        const updatedCard = this.buildDecisionCard(
          approval_id,
          "approved",
          userUpn,
        );
        return {
          statusCode: 200,
          type: "application/vnd.microsoft.card.adaptive",
          value: updatedCard,
        } as AdaptiveCardInvokeResponse;
      }

      if (verb === "reject") {
        await this.gateway.rejectProposal(approval_id, thread_id, userUpn);
        const updatedCard = this.buildDecisionCard(
          approval_id,
          "rejected",
          userUpn,
        );
        return {
          statusCode: 200,
          type: "application/vnd.microsoft.card.adaptive",
          value: updatedCard,
        } as AdaptiveCardInvokeResponse;
      }

      return {
        statusCode: 400,
        type: "application/vnd.microsoft.error",
        value: { code: "BadRequest", message: `Unknown verb: ${verb}` },
      } as AdaptiveCardInvokeResponse;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error";
      return {
        statusCode: 500,
        type: "application/vnd.microsoft.error",
        value: { code: "InternalError", message },
      } as AdaptiveCardInvokeResponse;
    }
  }

  /**
   * Build an in-place replacement card after approval decision (TEAMS-003).
   */
  private buildDecisionCard(
    approvalId: string,
    decision: string,
    operatorUpn: string,
  ): Record<string, unknown> {
    const color = decision === "approved" ? "good" : "attention";
    const title =
      decision === "approved"
        ? `Approved by ${operatorUpn}`
        : `Rejected by ${operatorUpn}`;
    return {
      $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
      type: "AdaptiveCard",
      version: "1.5",
      body: [
        {
          type: "TextBlock",
          text: title,
          weight: "Bolder",
          size: "Medium",
          color,
        },
        {
          type: "TextBlock",
          text: `Approval ID: ${approvalId}`,
          size: "Small",
          color: "default",
        },
      ],
    };
  }

  /**
   * Capture ConversationReference on bot installation (proactive messaging bootstrap).
   */
  async onInstallationUpdate(context: TurnContext): Promise<void> {
    const ref = TurnContext.getConversationReference(context.activity);
    const { setConversationReference } = await import("./services/proactive");
    setConversationReference(ref);
  }
}
