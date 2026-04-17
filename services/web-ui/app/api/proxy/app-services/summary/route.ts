import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/app-services/summary' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'GET' });
  try {
    const url = `${getApiGatewayUrl()}/api/v1/app-services/summary`;
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) {
      log.error('app-services summary upstream error', { status: res.status });
      return NextResponse.json({ error: data?.error ?? `Gateway error: ${res.status}` }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for app-services summary', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
