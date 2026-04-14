import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/finops/cost-forecast' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/finops/cost-forecast
 *
 * Proxies cost forecast requests to the API gateway.
 * Query params forwarded as-is (subscription_id, budget_name).
 *
 * Returns month-end forecast, burn rate percentage, budget comparison,
 * and over-budget flag (threshold: projected > budget × 1.10).
 *
 * On failure returns null forecast_month_end_usd gracefully.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/finops/cost-forecast${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, forecast_month_end_usd: null },
        { status: res.status }
      );
    }

    log.debug('proxy response', { forecast: data?.forecast_month_end_usd ?? null });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, forecast_month_end_usd: null },
      { status: 502 }
    );
  }
}
