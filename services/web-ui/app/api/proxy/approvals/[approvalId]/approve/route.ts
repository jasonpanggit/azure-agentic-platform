import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/approvals/approve' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/approvals/[approvalId]/approve
 *
 * Proxies approval confirmations to the API gateway.
 * Forwards the Authorization header from the browser (MSAL pass-through).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ approvalId: string }> }
): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { approvalId } = await params;
    const body = await request.json();
    log.info('approval action', { approvalId, action: 'approve' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/approvals/${encodeURIComponent(approvalId)}/approve`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { approvalId, status: res.status, detail: errorData?.detail });
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('proxy response', { approvalId, status: res.status });
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
