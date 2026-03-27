export interface AppConfig {
  botId: string;
  botPassword: string;
  apiGatewayInternalUrl: string;
  webUiPublicUrl: string;
  apiGatewayPublicUrl: string; // DEPRECATED post-Action.Execute migration; kept for forward-compatibility
  teamsChannelId: string;
  escalationIntervalMinutes: number;
  port: number;
}

export function loadConfig(): AppConfig {
  const botId = process.env.BOT_ID;
  if (!botId) throw new Error("BOT_ID environment variable is required");

  const botPassword = process.env.BOT_PASSWORD ?? "";

  const apiGatewayInternalUrl = process.env.API_GATEWAY_INTERNAL_URL;
  if (!apiGatewayInternalUrl)
    throw new Error("API_GATEWAY_INTERNAL_URL environment variable is required");

  const webUiPublicUrl = process.env.WEB_UI_PUBLIC_URL;
  if (!webUiPublicUrl)
    throw new Error("WEB_UI_PUBLIC_URL environment variable is required");

  // API_GATEWAY_PUBLIC_URL is not currently used in card action URLs (Action.Execute
  // sends data through the bot, not via direct HTTP). Kept in config for forward-
  // compatibility if future card types need direct api-gateway URLs.
  const apiGatewayPublicUrl = process.env.API_GATEWAY_PUBLIC_URL ?? "";

  const teamsChannelId = process.env.TEAMS_CHANNEL_ID ?? "";

  const escalationIntervalMinutes = parseInt(
    process.env.ESCALATION_INTERVAL_MINUTES ?? "15",
    10,
  );

  const port = parseInt(process.env.PORT ?? "3978", 10);

  return {
    botId,
    botPassword,
    apiGatewayInternalUrl,
    webUiPublicUrl,
    apiGatewayPublicUrl,
    teamsChannelId,
    escalationIntervalMinutes,
    port,
  };
}
