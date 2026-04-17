import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/locks/remediation-script' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    log.info('proxy request', { method: 'GET', query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/locks/remediation-script${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    );

    if (!res.ok) {
      const text = await res.text();
      log.error('upstream error', { status: res.status });
      return new NextResponse(text || `Gateway error: ${res.status}`, {
        status: res.status,
        headers: { 'Content-Type': 'text/plain' },
      });
    }

    const scriptText = await res.text();
    log.debug('proxy response', { bytes: scriptText.length });

    return new NextResponse(scriptText, {
      status: 200,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Disposition': 'attachment; filename="lock-remediation.sh"',
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return new NextResponse(`Failed to reach API gateway: ${message}`, {
      status: 502,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}
