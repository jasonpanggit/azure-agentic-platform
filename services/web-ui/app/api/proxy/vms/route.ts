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
      // VM endpoint doesn't exist yet in Phase 1 — return empty gracefully
      log.debug('vm endpoint not ready, returning empty list', { status: res.status });
      return NextResponse.json({ vms: [], total: 0, has_more: false });
    }

    const data = await res.json();
    log.debug('vm list response', { total: data?.total });
    return NextResponse.json(data);
  } catch (err) {
    // Backend not available — return empty so UI shows empty state, not error
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.debug('gateway unreachable, returning empty vm list', { error: message });
    return NextResponse.json({ vms: [], total: 0, has_more: false });
  }
}
