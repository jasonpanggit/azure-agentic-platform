import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/app-services' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptionId = searchParams.get('subscription_id') ?? '';
  const healthStatus = searchParams.get('health_status') ?? '';
  const appType = searchParams.get('app_type') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId, healthStatus, appType });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/app-services`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);
    if (healthStatus) url.searchParams.set('health_status', healthStatus);
    if (appType) url.searchParams.set('app_type', appType);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('app-services upstream error', { status: res.status });
      return NextResponse.json({ error: data?.error ?? `Gateway error: ${res.status}`, apps: [], total: 0 }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for app-services', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, apps: [], total: 0 }, { status: 502 });
  }
}
