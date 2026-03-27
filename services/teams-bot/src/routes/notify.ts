import { Router, Request, Response } from "express";
import type { AppConfig } from "../config";
import type { NotifyRequest, NotifyResponse } from "../types";
import { buildAlertCard } from "../cards/alert-card";
import { buildApprovalCard } from "../cards/approval-card";
import { buildOutcomeCard } from "../cards/outcome-card";
import { buildReminderCard } from "../cards/reminder-card";
import {
  sendProactiveCard,
  hasConversationReference,
} from "../services/proactive";

const VALID_CARD_TYPES = ["alert", "approval", "outcome", "reminder"] as const;

export function createNotifyRouter(config: AppConfig): Router {
  const router = Router();

  router.post(
    "/teams/internal/notify",
    async (req: Request, res: Response): Promise<void> => {
      // Pre-flight: check if bot is installed in any channel
      if (!hasConversationReference()) {
        const response: NotifyResponse = {
          ok: false,
          error: "Bot not installed in any channel yet",
        };
        res.status(503).json(response);
        return;
      }

      const body = req.body as Partial<NotifyRequest>;

      // Validate card_type
      if (
        !body.card_type ||
        !VALID_CARD_TYPES.includes(body.card_type as (typeof VALID_CARD_TYPES)[number])
      ) {
        const response: NotifyResponse = {
          ok: false,
          error: `Invalid or missing card_type. Must be one of: ${VALID_CARD_TYPES.join(", ")}`,
        };
        res.status(400).json(response);
        return;
      }

      // Validate payload
      if (!body.payload || typeof body.payload !== "object") {
        const response: NotifyResponse = {
          ok: false,
          error: "Missing or invalid payload",
        };
        res.status(400).json(response);
        return;
      }

      try {
        let card: Record<string, unknown>;

        switch (body.card_type) {
          case "alert":
            card = buildAlertCard(
              body.payload as Parameters<typeof buildAlertCard>[0],
              config.webUiPublicUrl,
            );
            break;
          case "approval":
            card = buildApprovalCard(
              body.payload as Parameters<typeof buildApprovalCard>[0],
            );
            break;
          case "outcome":
            card = buildOutcomeCard(
              body.payload as Parameters<typeof buildOutcomeCard>[0],
              config.webUiPublicUrl,
            );
            break;
          case "reminder":
            card = buildReminderCard(
              body.payload as Parameters<typeof buildReminderCard>[0],
              config.webUiPublicUrl,
            );
            break;
          default:
            // TypeScript exhaustiveness — should never reach here
            res.status(400).json({ ok: false, error: "Unknown card_type" });
            return;
        }

        const payloadObj = body.payload as unknown as Record<string, unknown>;
        const cardIdentifier =
          payloadObj?.incident_id ??
          payloadObj?.approval_id ??
          "unknown";
        console.log(
          `[notify] Sending ${body.card_type} card for ${cardIdentifier}`,
        );

        const result = await sendProactiveCard(card);
        const response: NotifyResponse = {
          ok: true,
          message_id: result.messageId,
        };
        res.status(200).json(response);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        const response: NotifyResponse = { ok: false, error: message };
        res.status(500).json(response);
      }
    },
  );

  return router;
}
