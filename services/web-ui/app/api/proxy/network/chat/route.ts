import { NextRequest } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/chat' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/network/chat
 *
 * SSE proxy: streams network topology AI chat responses from the API gateway.
 * Body: { message: string, subscription_ids?: string[], thread_id?: string, topology_context?: object }
 * Response: text/event-stream — data: {"token": "..."} chunks, terminated by data: [DONE]
 */
export async function POST(request: NextRequest): Promise<Response> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();
    log.info('network chat request', { has_thread_id: !!body.thread_id });

    const res = await fetch(`${apiGatewayUrl}/api/v1/network-topology/chat`, {
      method: 'POST',
      headers: {
        ...buildUpstreamHeaders(request.headers.get('Authorization')),
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120_000),
    });

    if (!res.ok || !res.body) {
      log.error('upstream error', { status: res.status });
      return new Response(
        `data: ${JSON.stringify({ error: `Gateway error: ${res.status}` })}\n\ndata: [DONE]\n\n`,
        {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        }
      );
    }

    return new Response(res.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return new Response(
      `data: ${JSON.stringify({ error: `Failed to reach API gateway: ${message}` })}\n\ndata: [DONE]\n\n`,
      {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }
    );
  }
}
