import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compute/az-coverage' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/compute/az-coverage
 *
 * Proxies AZ coverage findings requests to the API gateway.
 * Query params forwarded: subscription_id, has_zone_redundancy, resource_type
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const searchParams = req.nextUrl.searchParams;
  const subscriptionId = searchParams.get('subscription_id') ?? '';
  const hasZoneRedundancy = searchParams.get('has_zone_redundancy') ?? '';
  const resourceType = searchParams.get('resource_type') ?? '';

  log.info('proxy request', { method: 'GET', subscriptionId, hasZoneRedundancy, resourceType });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/compute/az-coverage`);
    if (subscriptionId) url.searchParams.set('subscription_id', subscriptionId);
    if (hasZoneRedundancy) url.searchParams.set('has_zone_redundancy', hasZoneRedundancy);
    if (resourceType) url.searchParams.set('resource_type', resourceType);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('az-coverage upstream error', { status: res.status, error: data?.detail ?? data?.error });
      return NextResponse.json(
        { error: data?.detail ?? data?.error ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    log.debug('az-coverage findings response', { count: Array.isArray(data) ? data.length : 0 });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for az-coverage findings', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
