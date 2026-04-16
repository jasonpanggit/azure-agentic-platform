import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/runbooks/tools' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/runbooks/tools
 *
 * Returns the list of available automation tool names from the API gateway.
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'GET' });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/runbooks/tools`);
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('runbooks/tools upstream error', { status: res.status });
      return NextResponse.json(
        { error: data?.detail ?? data?.error ?? `Gateway error: ${res.status}`, tools: [] },
        { status: res.status }
      );
    }

    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for runbooks/tools', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, tools: [] },
      { status: 502 }
    );
  }
}
