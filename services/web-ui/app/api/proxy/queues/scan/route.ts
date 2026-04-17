import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/queues/scan' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'POST' });
  try {
    const url = `${getApiGatewayUrl()}/api/v1/queues/scan`;
    const res = await fetch(url, {
      method: 'POST',
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(60000),
    });
    const data = await res.json();
    if (!res.ok) {
      log.error('queues scan upstream error', { status: res.status });
      return NextResponse.json({ error: data?.error ?? `Gateway error: ${res.status}` }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for queues scan', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
