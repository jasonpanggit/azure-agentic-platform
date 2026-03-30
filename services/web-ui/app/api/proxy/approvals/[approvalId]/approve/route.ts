import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function getApiGatewayUrl(): string {
  const url = process.env.API_GATEWAY_URL;
  if (!url) {
    if (process.env.NEXT_PUBLIC_DEV_MODE === 'true') {
      return 'http://localhost:8000';
    }
    throw new Error('API_GATEWAY_URL is not configured');
  }
  return url;
}

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

    const upstreamHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const authHeader = request.headers.get('Authorization');
    if (authHeader) {
      upstreamHeaders['Authorization'] = authHeader;
    }

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/approvals/${approvalId}/approve`,
      {
        method: 'POST',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
