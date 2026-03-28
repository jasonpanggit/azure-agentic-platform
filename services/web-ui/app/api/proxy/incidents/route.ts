import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';

/**
 * GET /api/proxy/incidents
 *
 * Proxies incident list requests to the API gateway.
 * Query params forwarded as-is (subscription, severity, status, etc.)
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();

    const res = await fetch(
      `${API_GATEWAY_URL}/api/v1/incidents${query ? `?${query}` : ''}`,
      {
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
