import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vms/eol' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/vms/eol
 *
 * Proxies batch EOL lookup requests to the API gateway.
 * Body: { os_names: string[] }
 * Returns: { results: [{ os_name, eol_date, is_eol, source }] }
 *
 * On failure returns an empty results array gracefully.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = await request.json();
    log.info('proxy request', { method: 'POST', os_count: body?.os_names?.length ?? 0 });

    const apiGatewayUrl = getApiGatewayUrl();
    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), true);

    const res = await fetch(`${apiGatewayUrl}/api/v1/vms/eol`, {
      method: 'POST',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json({ results: [] });
    }

    const data = await res.json();
    log.debug('proxy response', { results_count: data?.results?.length ?? 0 });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ results: [] });
  }
}
