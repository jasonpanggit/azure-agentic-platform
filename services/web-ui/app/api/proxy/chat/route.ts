import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/chat
 *
 * Proxies chat messages from the web UI to the API gateway.
 * Forwards the Authorization header from the browser (MSAL pass-through).
 * Body: { message: string, thread_id?: string, subscription_ids?: string[] }
 * Response: { thread_id: string }
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(`${apiGatewayUrl}/api/v1/chat`, {
      method: 'POST',
      headers: upstreamHeaders,
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
