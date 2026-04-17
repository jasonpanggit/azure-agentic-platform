import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compute/disks' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/compute/disks?subscription_id=&resource_type=
 * Returns orphaned disk and snapshot findings from the last scan.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = request.nextUrl;
    const qs = searchParams.toString();

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/compute/disks/orphaned${qs ? `?${qs}` : ''}`,
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

    log.info('disk findings fetched', { total: data?.total });
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
