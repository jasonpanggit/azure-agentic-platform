import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/topology' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/topology
 *
 * Proxies topology tree requests to the API gateway ARG endpoint.
 * Replaces the old direct-ARM /api/topology route.
 *
 * Query params forwarded: subscriptions
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptions = searchParams.get('subscriptions') ?? '';

  log.info('proxy request', { method: 'GET', subscriptions });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/topology/tree`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      log.warn('upstream error', { status: res.status });
      return NextResponse.json(
        { error: `Upstream error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('topology response', { node_count: data?.nodes?.length });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('proxy error', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
