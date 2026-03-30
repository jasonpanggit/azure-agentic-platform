import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/approvals/[approvalId]/reject
 *
 * Proxies approval rejections to the API gateway.
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

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/approvals/${encodeURIComponent(approvalId)}/reject`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
