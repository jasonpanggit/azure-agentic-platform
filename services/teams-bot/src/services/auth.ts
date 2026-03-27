import { DefaultAzureCredential } from "@azure/identity";

let credential: DefaultAzureCredential | null = null;

function getCredential(): DefaultAzureCredential {
  if (!credential) {
    credential = new DefaultAzureCredential();
  }
  return credential;
}

/**
 * Check whether the bot is running in development mode.
 *
 * Dev mode is active when AZURE_CLIENT_ID env var is NOT set —
 * same pattern as the api-gateway (auth.py).
 */
export function isDevelopmentMode(): boolean {
  return !process.env.AZURE_CLIENT_ID;
}

/**
 * Acquire a Bearer token for the api-gateway.
 *
 * In production: uses DefaultAzureCredential (resolved from system-assigned
 * managed identity on Container Apps) to get a token scoped to the api-gateway.
 *
 * In development (no AZURE_CLIENT_ID): returns "dev-token" to enable local testing.
 */
export async function getGatewayToken(apiGatewayClientId?: string): Promise<string> {
  if (isDevelopmentMode()) {
    return "dev-token";
  }

  const scope = apiGatewayClientId
    ? `api://${apiGatewayClientId}/.default`
    : "https://management.azure.com/.default";

  const cred = getCredential();
  const tokenResponse = await cred.getToken(scope);
  if (!tokenResponse?.token) {
    throw new Error("Failed to acquire token for api-gateway");
  }
  return tokenResponse.token;
}
