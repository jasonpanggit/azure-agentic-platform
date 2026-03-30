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
 * GET /api/proxy/chat/result?thread_id=<id>
 *
 * Polls the API gateway for the Foundry run status on a given thread.
 * Forwards the Authorization header from the browser (MSAL pass-through).
 * Returns: { thread_id, run_status, reply? }
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const threadId = searchParams.get('thread_id');
  const runId = searchParams.get('run_id');

  if (!threadId) {
    return NextResponse.json({ error: 'Missing thread_id parameter' }, { status: 400 });
  }

  try {
    const apiGatewayUrl = getApiGatewayUrl();

    const upstreamHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const authHeader = request.headers.get('Authorization');
    if (authHeader) {
      upstreamHeaders['Authorization'] = authHeader;
    }

    const runIdParam = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    const res = await fetch(
      `${apiGatewayUrl}/api/v1/chat/${encodeURIComponent(threadId)}/result${runIdParam}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(10000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
