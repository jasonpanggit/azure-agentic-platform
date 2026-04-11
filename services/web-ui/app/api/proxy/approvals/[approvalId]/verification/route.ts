import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/approvals/verification' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/approvals/[approvalId]/verification
 *
 * Proxies verification result polling to the API gateway.
 * Returns 202 with Retry-After when verification is still pending.
 * Returns 200 with RemediationAuditRecord when verification is complete.
 * Returns 404 when no execution record exists.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ approvalId: string }> }
): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { approvalId } = await params;
    log.info('verification poll', { approvalId });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/approvals/${encodeURIComponent(approvalId)}/verification`,
      {
        method: 'GET',
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    if (res.status === 202) {
      const data = await res.json();
      log.debug('verification pending', { approvalId });
      return NextResponse.json(data, {
        status: 202,
        headers: { 'Retry-After': res.headers.get('Retry-After') || '60' },
      });
    }

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { approvalId, status: res.status, detail: errorData?.detail });
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('verification result', { approvalId, result: data?.verification_result });
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
