import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compute/az-coverage/summary' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/compute/az-coverage/summary
 *
 * Proxies AZ coverage summary request to the API gateway.
 * Query params forwarded: subscription_id
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const subscriptionId = req.nextUrl.searchParams.get('subscription_id') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/compute/az-coverage/summary`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('az-coverage summary upstream error', { status: res.status, error: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, total: 0, zone_redundant: 0, non_redundant: 0, coverage_pct: 0 },
        { status: res.status }
      );
    }

    log.debug('az-coverage summary response', { total: data?.total, coverage_pct: data?.coverage_pct });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for az-coverage summary', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, total: 0, zone_redundant: 0, non_redundant: 0, coverage_pct: 0 },
      { status: 502 }
    );
  }
}
