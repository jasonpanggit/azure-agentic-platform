import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/lb/summary' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/network/lb/summary
 *
 * Proxies LB health summary request to the API gateway.
 * Query params forwarded: subscription_id
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const subscriptionId = req.nextUrl.searchParams.get('subscription_id') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/network/lb/summary`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('lb summary upstream error', { status: res.status, error: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, total: 0, by_severity: {}, basic_sku_count: 0 },
        { status: res.status }
      );
    }

    log.debug('lb summary response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for lb summary', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, total: 0, by_severity: {}, basic_sku_count: 0 },
      { status: 502 }
    );
  }
}
