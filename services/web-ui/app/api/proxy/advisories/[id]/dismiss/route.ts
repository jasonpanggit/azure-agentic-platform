import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/advisories/[id]/dismiss' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * PATCH /api/proxy/advisories/[id]/dismiss
 *
 * Proxies advisory dismiss requests to the API gateway.
 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  try {
    const { id } = await params;
    const apiGatewayUrl = getApiGatewayUrl();
    log.info('proxy request', { method: 'PATCH', id });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/advisories/${id}/dismiss`,
      {
        method: 'PATCH',
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, id });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, success: false },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, success: false },
      { status: 502 }
    );
  }
}
