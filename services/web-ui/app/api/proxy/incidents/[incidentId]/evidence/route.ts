import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/incidents/[incidentId]/evidence' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/incidents/[incidentId]/evidence
 *
 * Proxies evidence requests to the API gateway.
 * Returns 202 with Retry-After header when the diagnostic pipeline is still running.
 * Returns 200 with evidence payload when the pipeline has completed.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ incidentId: string }> }
): Promise<NextResponse> {
  const { incidentId } = await params;
  log.info('proxy request', { method: 'GET', incidentId });

  try {
    const url = `${getApiGatewayUrl()}/api/v1/incidents/${incidentId}/evidence`;
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url, {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    if (res.status === 202) {
      log.debug('pipeline pending', { incidentId });
      return NextResponse.json(
        { pipeline_status: 'pending' },
        {
          status: 202,
          headers: { 'Retry-After': res.headers.get('Retry-After') ?? '5' },
        }
      );
    }

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, incidentId, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.debug('evidence ready', { incidentId, status: res.status });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message, incidentId });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
