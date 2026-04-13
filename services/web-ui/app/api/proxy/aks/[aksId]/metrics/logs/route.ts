import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks/[aksId]/metrics/logs' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ aksId: string }> }
): Promise<NextResponse> {
  const { aksId } = await params;
  const searchParams = req.nextUrl.searchParams;
  const timespan = searchParams.get('timespan') ?? 'PT24H';
  const interval = searchParams.get('interval') ?? 'PT5M';

  log.info('proxy request', { aksId: aksId.slice(0, 40), timespan });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/aks/${encodeURIComponent(aksId)}/metrics/logs`);
    url.searchParams.set('timespan', timespan);
    url.searchParams.set('interval', interval);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(30000),
    });

    if (!res.ok) {
      log.warn('la metrics fetch failed', { status: res.status });
      return NextResponse.json({ resource_id: '', timespan, metrics: [], source: 'log_analytics' });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.warn('la metrics unavailable', { error: message });
    return NextResponse.json({ resource_id: '', timespan, metrics: [], source: 'log_analytics' });
  }
}
