import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/lb/scan' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/network/lb/scan
 *
 * Triggers an on-demand LB health scan via the API gateway.
 * Returns { scanned, status, duration_ms }.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    log.info('proxy request', { method: 'POST' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(`${getApiGatewayUrl()}/api/v1/network/lb/scan`, {
      method: 'POST',
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(60000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.info('lb scan triggered', { scanned: data?.scanned });
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
