import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/runbooks' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/runbooks
 *
 * Proxies runbook search requests to the API gateway.
 * Returns an empty list gracefully when the backend is unavailable.
 *
 * Query params forwarded: query, domain, limit
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const query = searchParams.get('query') ?? '';
  const domain = searchParams.get('domain') ?? '';
  const limit = searchParams.get('limit') ?? '12';

  log.info('proxy request', { method: 'GET', query, domain, limit });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/runbooks/search`);
    url.searchParams.set('query', query); // always send — backend requires this param
    if (domain) url.searchParams.set('domain', domain);
    url.searchParams.set('limit', limit);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('runbooks upstream error', { status: res.status, error: data?.detail ?? data?.error });
      return NextResponse.json(
        { error: data?.detail ?? data?.error ?? `Gateway error: ${res.status}`, results: [] },
        { status: res.status }
      );
    }

    log.debug('runbooks search response', { count: Array.isArray(data) ? data.length : data?.results?.length });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for runbooks search', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, results: [] },
      { status: 502 }
    );
  }
}
