import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vms/[vmId]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ vmId: string }> }
): Promise<NextResponse> {
  const { vmId } = await params;
  log.info('proxy request', { vmId: vmId.slice(0, 40) });

  try {
    const url = `${getApiGatewayUrl()}/api/v1/vms/${encodeURIComponent(vmId)}`;
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url, {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();

    if (!res.ok) {
      log.error('upstream error', { status: res.status });
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
