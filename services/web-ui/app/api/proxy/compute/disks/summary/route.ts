import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compute/disks/summary' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/compute/disks/summary?subscription_id=
 * Returns aggregated disk waste summary.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = request.nextUrl;
    const qs = searchParams.toString();

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/compute/disks/summary${qs ? `?${qs}` : ''}`,
      {
        method: 'GET',
        headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.info('summary fetched', { orphaned_disks: data?.orphaned_disks });
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
