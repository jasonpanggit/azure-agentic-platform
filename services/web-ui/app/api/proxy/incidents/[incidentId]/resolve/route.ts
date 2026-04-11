import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/incidents/resolve' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/incidents/[incidentId]/resolve
 *
 * Proxies incident resolution to the API gateway.
 * Called by VerificationCard "Yes, resolved" button (LOOP-002).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ incidentId: string }> }
): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { incidentId } = await params;
    const body = await request.json();
    log.info('resolve incident', { incidentId });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/resolve`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { incidentId, status: res.status, detail: errorData?.detail });
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('incident resolved', { incidentId });
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
