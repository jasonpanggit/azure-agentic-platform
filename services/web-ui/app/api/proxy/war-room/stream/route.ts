import { NextRequest } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/war-room/stream' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/war-room/stream?incident_id=<id>
 *
 * Pipes the upstream SSE stream from the API gateway to the browser.
 * Adds Authorization header (not possible from browser EventSource).
 */
export async function GET(request: NextRequest): Promise<Response> {
  const { searchParams } = new URL(request.url);
  const incidentId = searchParams.get('incident_id');
  if (!incidentId) {
    return new Response('incident_id is required', { status: 400 });
  }

  const apiGatewayUrl = getApiGatewayUrl();
  const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);
  log.info('sse stream connect', { incident_id: incidentId });

  const upstream = await fetch(
    `${apiGatewayUrl}/api/v1/incidents/${encodeURIComponent(incidentId)}/war-room/stream`,
    {
      headers: upstreamHeaders,
      // No AbortSignal.timeout here — SSE streams are long-lived by design
    }
  );

  if (!upstream.ok || !upstream.body) {
    log.error('upstream sse error', { status: upstream.status });
    return new Response('Failed to connect to war room stream', { status: upstream.status });
  }

  // Pipe the upstream SSE body verbatim to the browser
  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    },
  });
}
