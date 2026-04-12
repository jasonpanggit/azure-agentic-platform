import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/aks
 *
 * Proxies AKS cluster inventory requests to the API gateway.
 * Returns an empty list gracefully when the backend endpoint is unavailable.
 *
 * Query params forwarded: subscriptions, search
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptions = searchParams.get('subscriptions') ?? '';
  const search = searchParams.get('search') ?? '';

  log.info('proxy request', { method: 'GET', subscriptions, search });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/aks`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);
    if (search) url.searchParams.set('search', search);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('aks upstream error', { status: res.status, error: data?.detail ?? data?.error });
      return NextResponse.json(
        { error: data?.detail ?? data?.error ?? `Gateway error: ${res.status}`, clusters: [], total: 0 },
        { status: res.status }
      );
    }

    log.debug('aks list response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for aks list', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, clusters: [], total: 0 },
      { status: 502 }
    );
  }
}
