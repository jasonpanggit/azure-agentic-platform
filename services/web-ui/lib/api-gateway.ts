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
