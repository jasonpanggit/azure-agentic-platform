import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/subscriptions/[id]/stats' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/subscriptions/[id]/stats
 *
 * Proxies subscription stats to the API gateway.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  try {
    const { id } = await params;
    const apiGatewayUrl = getApiGatewayUrl();
    log.info('proxy request', { method: 'GET', id });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/subscriptions/${id}/stats`,
      {
        headers: upstreamHeaders,
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

    log.debug('stats fetched', { id });
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
