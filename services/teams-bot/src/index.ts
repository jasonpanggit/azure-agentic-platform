import express from "express";
import {
  CloudAdapter,
  ConfigurationBotFrameworkAuthentication,
} from "botbuilder";
import { loadConfig } from "./config";
import { healthRouter } from "./routes/health";
import { createNotifyRouter } from "./routes/notify";
import { AapTeamsBot } from "./bot";
import { GatewayClient } from "./services/gateway-client";
import { initializeProactive } from "./services/proactive";

const config = loadConfig();
const app = express();

app.use(express.json());

// Routes
app.use(healthRouter);
app.use(createNotifyRouter(config));

// Bot Framework adapter (TEAMS-001)
const botFrameworkAuth = new ConfigurationBotFrameworkAuthentication({
  MicrosoftAppId: config.botId,
  MicrosoftAppPassword: config.botPassword,
  MicrosoftAppType: "SingleTenant",
  MicrosoftAppTenantId: process.env.BOT_TENANT_ID ?? "",
});

const adapter = new CloudAdapter(botFrameworkAuth);

// Error handler — sends a user-friendly message on turn errors
adapter.onTurnError = async (context, error) => {
  console.error("[bot] Turn error:", error);
  await context.sendActivity("An error occurred. Please try again.");
};

// Gateway client for api-gateway integration
const gateway = new GatewayClient(
  config.apiGatewayInternalUrl,
  process.env.API_GATEWAY_CLIENT_ID,
);

// Bot instance
const bot = new AapTeamsBot(gateway);

// Initialize proactive messaging with the adapter
initializeProactive(adapter, config.botId);

// Bot Framework messaging endpoint
app.post("/api/messages", async (req, res) => {
  await adapter.process(req, res, async (context) => {
    await bot.run(context);
  });
});

app.listen(config.port, () => {
  console.log(`Teams bot listening on port ${config.port}`);
});

export { app }; // For testing
