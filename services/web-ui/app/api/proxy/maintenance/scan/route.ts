import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/maintenance/scan' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/maintenance/scan
 * Triggers a live ARG scan for maintenance events across managed subscriptions.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    log.info('proxy request', { method: 'POST' });

    const res = await fetch(`${apiGatewayUrl}/api/v1/maintenance/scan`, {
      method: 'POST',
      headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(30000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json({ error: data?.detail ?? `Gateway error: ${res.status}` }, { status: res.status });
    }

    log.info('scan complete', { events_found: data?.events_found });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
