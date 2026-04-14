import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/finops/ri-utilization' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/finops/ri-utilization
 *
 * Proxies Reserved Instance utilisation requests to the API gateway.
 * Query params forwarded as-is (subscription_id).
 *
 * Returns RI benefit consumed via amortized-delta method (AmortizedCost − ActualCost)
 * at subscription scope — no Billing Reader role required.
 *
 * On failure returns null ri_benefit_estimated_usd gracefully.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/finops/ri-utilization${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, ri_benefit_estimated_usd: null },
        { status: res.status }
      );
    }

    log.debug('proxy response', { ri_benefit: data?.ri_benefit_estimated_usd ?? null });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, ri_benefit_estimated_usd: null },
      { status: 502 }
    );
  }
}
