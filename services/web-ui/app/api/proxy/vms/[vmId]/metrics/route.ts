import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vms/[vmId]/metrics' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ vmId: string }> }
): Promise<NextResponse> {
  const { vmId } = await params;
  const searchParams = req.nextUrl.searchParams;
  const metrics = searchParams.get('metrics') ?? '';
  const timespan = searchParams.get('timespan') ?? 'PT24H';
  const interval = searchParams.get('interval') ?? 'PT5M';

  log.info('proxy request', { vmId: vmId.slice(0, 40), timespan });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/vms/${encodeURIComponent(vmId)}/metrics`);
    if (metrics) url.searchParams.set('metrics', metrics);
    url.searchParams.set('timespan', timespan);
    url.searchParams.set('interval', interval);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(30000), // metrics can be slow
    });

    if (!res.ok) {
      // Return empty metrics on error — panel shows empty chart, not crash
      log.warn('metrics fetch failed', { status: res.status });
      return NextResponse.json({ resource_id: '', timespan, interval, metrics: [] });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.warn('metrics unavailable', { error: message });
    return NextResponse.json({ resource_id: '', timespan, interval, metrics: [] });
  }
}
