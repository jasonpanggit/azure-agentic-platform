import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/reports/shift-handover' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/reports/shift-handover
 *
 * Proxies shift handover report generation to the API gateway.
 * Body: { shift_hours?: number, format?: "json" | "markdown" }
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.text();
    log.info('proxy request', { method: 'POST' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(`${apiGatewayUrl}/api/v1/reports/shift-handover`, {
      method: 'POST',
      headers: {
        ...upstreamHeaders,
        'Content-Type': 'application/json',
      },
      body,
      signal: AbortSignal.timeout(30000),
    });

    if (res.headers.get('content-type')?.includes('text/plain')) {
      const text = await res.text();
      return new NextResponse(text, {
        status: res.status,
        headers: { 'Content-Type': 'text/plain' },
      });
    }

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status },
      );
    }

    log.debug('proxy response', { report_id: data?.report_id });
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 },
    );
  }
}
