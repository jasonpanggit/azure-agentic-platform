import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/agents/health
 *
 * Proxies agent health summary from the API gateway.
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  try {
    const base = getApiGatewayUrl();
    const upstream = `${base}/api/v1/agents/health`;
    const res = await fetch(upstream, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json(
        { error: `Upstream error: ${res.status}`, detail: text },
        { status: res.status },
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: 'Failed to fetch agent health', detail: String(err) },
      { status: 502 },
    );
  }
}
