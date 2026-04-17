import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/queues' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptionId = searchParams.get('subscription_id') ?? '';
  const healthStatus = searchParams.get('health_status') ?? '';
  const namespaceType = searchParams.get('namespace_type') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId, healthStatus, namespaceType });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/queues`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);
    if (healthStatus) url.searchParams.set('health_status', healthStatus);
    if (namespaceType) url.searchParams.set('namespace_type', namespaceType);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('queues upstream error', { status: res.status });
      return NextResponse.json({ error: data?.error ?? `Gateway error: ${res.status}`, namespaces: [], total: 0 }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for queues', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, namespaces: [], total: 0 }, { status: 502 });
  }
}
