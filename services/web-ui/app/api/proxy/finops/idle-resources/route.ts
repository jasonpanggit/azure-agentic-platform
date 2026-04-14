import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/finops/idle-resources' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/finops/idle-resources
 *
 * Proxies idle resource detection requests to the API gateway.
 * Query params forwarded as-is (subscription_id, threshold_cpu_pct, hours).
 *
 * Returns list of idle VMs (CPU <2% AND network <1MB/s for 72h) with
 * monthly cost estimates and HITL deallocation proposal approval IDs.
 *
 * On failure returns empty idle_resources array gracefully.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/finops/idle-resources${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, idle_count: 0, idle_resources: [] },
        { status: res.status }
      );
    }

    log.debug('proxy response', { idle_count: data?.idle_count ?? 0 });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, idle_count: 0, idle_resources: [] },
      { status: 502 }
    );
  }
}
