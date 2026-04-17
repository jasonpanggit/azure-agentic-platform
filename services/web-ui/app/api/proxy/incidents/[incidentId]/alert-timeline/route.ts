import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/incidents/[incidentId]/alert-timeline' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/incidents/[incidentId]/alert-timeline
 *
 * Proxies alert-timeline requests to the API gateway.
 * Returns the full change-correlation story for a single incident.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ incidentId: string }> }
): Promise<NextResponse> {
  try {
    const { incidentId } = await params;
    const apiGatewayUrl = getApiGatewayUrl();
    log.info('proxy request', { method: 'GET', incidentId });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/alert-timeline`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, incidentId, detail: data?.detail ?? data?.error });
      return NextResponse.json(
        { error: data?.error ?? data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.debug('proxy response', { incidentId, correlation_count: data?.change_correlations?.length ?? 0 });
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
