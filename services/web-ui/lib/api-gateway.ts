/**
 * API Gateway URL utilities for server-side proxy routes.
 */

/**
 * Returns the API Gateway URL from environment.
 * - In production: reads API_GATEWAY_URL (throws if unset → proxy returns 502)
 * - In dev mode: falls back to http://localhost:8000
 */
export function getApiGatewayUrl(): string {
  const url = process.env.API_GATEWAY_URL;
  if (!url) {
    if (process.env.NEXT_PUBLIC_DEV_MODE === 'true') {
      return 'http://localhost:8000';
    }
    throw new Error('API_GATEWAY_URL is not configured');
  }
  return url;
}

/**
 * Build upstream headers for proxy requests.
 * Forwards Authorization from the incoming request if present.
 *
 * Expected Authorization format: "Bearer <entra-id-token>"
 * The token must be acquired for scope: api://{API_GATEWAY_CLIENT_ID}/incidents.write
 * (see lib/msal-config.ts gatewayTokenRequest — used by ChatDrawer and other components
 * that call acquireTokenSilent before making API requests).
 *
 * The API gateway EntraTokenValidator (services/api-gateway/auth.py) validates the
 * audience (api://{client_id}) and the tenant, then returns decoded claims.
 */
export function buildUpstreamHeaders(
  authHeader: string | null,
  includeContentType = true
): Record<string, string> {
  const headers: Record<string, string> = {};
  if (includeContentType) {
    headers['Content-Type'] = 'application/json';
  }
  if (authHeader) {
    headers['Authorization'] = authHeader;
  }
  return headers;
}
