import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/network/lb' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/network/lb
 *
 * Proxies LB health findings requests to the API gateway.
 * Query params forwarded: subscription_id, severity
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptionId = searchParams.get('subscription_id') ?? '';
  const severity = searchParams.get('severity') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId, severity });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/network/lb`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);
    if (severity) url.searchParams.set('severity', severity);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('lb upstream error', { status: res.status, error: data?.detail ?? data?.error });
      return NextResponse.json(
        { error: data?.detail ?? data?.error ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.debug('lb findings response', { count: Array.isArray(data) ? data.length : 0 });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for lb findings', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
