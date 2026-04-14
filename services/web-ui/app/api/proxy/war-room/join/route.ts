import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/war-room/join' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/war-room/join?incident_id=<id>
 * Body: { display_name?, role? }
 *
 * Proxies to POST /api/v1/incidents/{id}/war-room
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const incidentId = searchParams.get('incident_id');
    if (!incidentId) {
      return NextResponse.json({ error: 'incident_id is required' }, { status: 400 });
    }
    const body = await request.text();
    log.info('proxy request', { method: 'POST', incident_id: incidentId });
    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room`,
      {
        method: 'POST',
        headers: { ...upstreamHeaders, 'Content-Type': 'application/json' },
        body: body || '{}',
        signal: AbortSignal.timeout(15000),
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
