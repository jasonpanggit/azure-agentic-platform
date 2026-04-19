import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/database/health' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptionId = searchParams.get('subscription_id') ?? '';
  const dbType = searchParams.get('db_type') ?? '';
  const healthStatus = searchParams.get('health_status') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId, dbType, healthStatus });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/database/health`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);
    if (dbType) url.searchParams.set('db_type', dbType);
    if (healthStatus) url.searchParams.set('health_status', healthStatus);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('database/health upstream error', { status: res.status });
      return NextResponse.json({ error: data?.error ?? `Gateway error: ${res.status}`, databases: [], total: 0 }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for database/health', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, databases: [], total: 0 }, { status: 502 });
  }
}
