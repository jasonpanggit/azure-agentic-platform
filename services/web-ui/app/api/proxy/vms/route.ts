import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vms' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/vms
 *
 * Proxies VM inventory requests to the API gateway.
 * Returns an empty list gracefully when the backend endpoint doesn't exist yet
 * (Phase 2 backend). This avoids a blocking dependency between frontend and backend phases.
 *
 * Query params forwarded: subscriptions, status, search
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptions = searchParams.get('subscriptions') ?? '';
  const status = searchParams.get('status') ?? 'all';
  const search = searchParams.get('search') ?? '';

  log.info('proxy request', { method: 'GET', subscriptions, status, search });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/vms`);
    if (subscriptions) url.searchParams.set('subscriptions', subscriptions);
    if (status !== 'all') url.searchParams.set('status', status);
    if (search) url.searchParams.set('search', search);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      const body = await res.text().catch(() => '');
      log.error('vm upstream error', { status: res.status, body });
      return NextResponse.json(
        { error: `upstream error ${res.status}`, vms: [], total: 0, has_more: false },
        { status: res.status >= 500 ? 502 : res.status },
      );
    }

    const data = await res.json();
    log.debug('vm list response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    const isTimeout = message.includes('timeout') || message.includes('abort');
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, vms: [], total: 0, has_more: false },
      { status: isTimeout ? 504 : 502 },
    );
  }
}
