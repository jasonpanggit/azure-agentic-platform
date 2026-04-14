import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/war-room/heartbeat' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/war-room/heartbeat?incident_id=<id>
 *
 * Proxies presence heartbeat to POST /api/v1/incidents/{id}/war-room/heartbeat
 * Uses a short 5s timeout — heartbeats must be fast.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const incidentId = searchParams.get('incident_id');
    if (!incidentId) {
      return NextResponse.json({ error: 'incident_id is required' }, { status: 400 });
    }
    log.info('proxy request', { method: 'POST', incident_id: incidentId });
    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room/heartbeat`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(5000),
      }
    );
    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}` }, { status: res.status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
