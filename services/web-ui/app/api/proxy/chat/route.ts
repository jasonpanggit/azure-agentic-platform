import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/chat' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/chat
 *
 * Proxies chat messages from the web UI to the API gateway.
 * Forwards the Authorization header from the browser (MSAL pass-through).
 * Body: { message: string, thread_id?: string, subscription_ids?: string[] }
 * Response: { thread_id: string }
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();
    log.info('proxy request', { method: 'POST', has_thread_id: !!body.thread_id });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    // The gateway POST /api/v1/chat is now synchronous (Responses API) —
    // it blocks until the orchestrator produces a reply. Allow up to 120s
    // for complex multi-agent queries before timing out.
    const res = await fetch(`${apiGatewayUrl}/api/v1/chat`, {
      method: 'POST',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120_000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.debug('proxy response', { status: res.status });
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
