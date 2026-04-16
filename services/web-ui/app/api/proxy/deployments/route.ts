import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/deployments' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/deployments
 *
 * Proxies deployment list requests to the API gateway.
 * Query params forwarded as-is (resource_group, limit, hours_back).
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/deployments${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, deployments: [], total: 0 },
        { status: res.status }
      );
    }

    log.debug('proxy response', { total: data?.total ?? 0 });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, deployments: [], total: 0 },
      { status: 502 }
    );
  }
}

/**
 * POST /api/proxy/deployments
 *
 * Proxies deployment ingestion requests (GitHub webhook / direct POST).
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.text();
    log.info('proxy request', { method: 'POST' });

    // Forward GitHub webhook headers if present
    const upstreamHeaders: Record<string, string> = {
      ...buildUpstreamHeaders(request.headers.get('Authorization'), false),
      'Content-Type': 'application/json',
    };
    const githubEvent = request.headers.get('X-GitHub-Event');
    const githubDelivery = request.headers.get('X-GitHub-Delivery');
    if (githubEvent) upstreamHeaders['X-GitHub-Event'] = githubEvent;
    if (githubDelivery) upstreamHeaders['X-GitHub-Delivery'] = githubDelivery;

    const res = await fetch(`${apiGatewayUrl}/api/v1/deployments`, {
      method: 'POST',
      headers: upstreamHeaders,
      body,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json(data, { status: res.status });
    }

    log.debug('proxy response', { deployment_id: data?.deployment_id });
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
