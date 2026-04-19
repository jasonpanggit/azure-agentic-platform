import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/database/slow-queries' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptionId = searchParams.get('subscription_id') ?? '';
  const dbType = searchParams.get('db_type') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId, dbType });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/database/slow-queries`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);
    if (dbType) url.searchParams.set('db_type', dbType);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('database/slow-queries upstream error', { status: res.status });
      return NextResponse.json({ error: data?.error ?? `Gateway error: ${res.status}`, servers: [], total: 0 }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for database/slow-queries', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, servers: [], total: 0 }, { status: 502 });
  }
}
