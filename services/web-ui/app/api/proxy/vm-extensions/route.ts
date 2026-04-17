import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    const upstream = `${getApiGatewayUrl()}/api/v1/vm-extensions${query ? `?${query}` : ''}`;
    const res = await fetch(upstream, {
      headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}`, findings: [] }, { status: res.status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, findings: [] }, { status: 502 });
  }
}
