import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/notifications/subscribe' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/notifications/subscribe
 *
 * Stores a Web Push subscription by proxying to the API gateway.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();
    log.info('proxy request', { method: 'POST' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(`${apiGatewayUrl}/api/v1/notifications/subscribe`, {
      method: 'POST',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { status: res.status, detail: (errorData as { detail?: string })?.detail });
      return NextResponse.json(
        { error: (errorData as { detail?: string })?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('proxy response', { status: res.status });
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

/**
 * DELETE /api/proxy/notifications/subscribe
 *
 * Removes a Web Push subscription by proxying to the API gateway.
 */
export async function DELETE(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();
    log.info('proxy request', { method: 'DELETE' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(`${apiGatewayUrl}/api/v1/notifications/subscribe`, {
      method: 'DELETE',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json().catch(() => ({}));
    log.debug('proxy response', { status: res.status });
    return NextResponse.json(data, { status: res.ok ? 200 : res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
