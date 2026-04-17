import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/backup/summary' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    log.info('proxy request', { method: 'GET' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/backup/summary`,
      { headers: upstreamHeaders, signal: AbortSignal.timeout(15000) }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, total_vms: 0, protected: 0, unprotected: 0, unhealthy: 0, protection_rate: 0, recent_failures: 0 },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, total_vms: 0, protected: 0, unprotected: 0, unhealthy: 0, protection_rate: 0, recent_failures: 0 },
      { status: 502 }
    );
  }
}
