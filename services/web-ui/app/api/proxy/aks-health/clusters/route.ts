import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks-health/clusters' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscription_id = searchParams.get('subscription_id') ?? '';
  const health_status = searchParams.get('health_status') ?? '';

  log.info('proxy request', { method: 'GET', subscription_id, health_status });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/aks-health/clusters`);
    if (subscription_id) url.searchParams.set('subscription_id', subscription_id);
    if (health_status) url.searchParams.set('health_status', health_status);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}`, clusters: [], total: 0 }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, clusters: [], total: 0 }, { status: 502 });
  }
}
