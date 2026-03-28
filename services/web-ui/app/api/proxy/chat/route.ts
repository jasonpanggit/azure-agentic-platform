import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';

/**
 * POST /api/proxy/chat
 *
 * Proxies chat messages from the web UI to the API gateway.
 * Body: { message: string, thread_id?: string, subscription_ids?: string[] }
 * Response: { thread_id: string }
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = await request.json();

    const res = await fetch(`${API_GATEWAY_URL}/api/v1/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });

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
