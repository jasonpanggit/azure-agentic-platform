import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/war-room/handoff' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/war-room/handoff?incident_id=<id>
 *
 * Proxies shift-handoff summary generation to POST /api/v1/incidents/{id}/war-room/handoff
 * Uses 45s timeout — GPT-4o can take up to 30s for handoff summarisation.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const incidentId = searchParams.get('incident_id');
    if (!incidentId) {
      return NextResponse.json({ error: 'incident_id is required', summary: null }, { status: 400 });
    }
    log.info('proxy request', { method: 'POST', incident_id: incidentId });
    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room/handoff`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(45000),
      }
    );
    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}`, summary: null }, { status: res.status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}`, summary: null }, { status: 502 });
  }
}
