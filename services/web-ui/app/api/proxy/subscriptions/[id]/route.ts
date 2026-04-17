import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/subscriptions/[id]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * PATCH /api/proxy/subscriptions/[id]
 *
 * Proxies subscription update (label, monitoring_enabled, environment) to the API gateway.
 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  try {
    const { id } = await params;
    const apiGatewayUrl = getApiGatewayUrl();
    log.info('proxy request', { method: 'PATCH', id });

    const body = await request.json();
    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), true);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/subscriptions/${id}`,
      {
        method: 'PATCH',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, id, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.debug('patch complete', { id });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
