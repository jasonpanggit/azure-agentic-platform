import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface RouteParams {
  params: Promise<{ name: string }>;
}

/**
 * POST /api/proxy/agents/[name]/check
 *
 * Forces an immediate health check for the named agent.
 */
export async function POST(req: NextRequest, { params }: RouteParams): Promise<NextResponse> {
  const { name } = await params;
  try {
    const base = getApiGatewayUrl();
    const upstream = `${base}/api/v1/agents/${encodeURIComponent(name)}/check`;
    const res = await fetch(upstream, {
      method: 'POST',
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
      { error: 'Failed to force check agent', detail: String(err) },
      { status: 502 },
    );
  }
}
