import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/vmss/[vmssId]/diagnostic-settings' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ vmssId: string }> }
): Promise<NextResponse> {
  const { vmssId } = await params;
  log.info('check VMSS diagnostic settings', { vmssId: vmssId.slice(0, 40) });

  try {
    const { searchParams } = new URL(req.url);
    const query = searchParams.toString();
    const qs = query ? `?${query}` : '';
    const url = `${getApiGatewayUrl()}/api/v1/vmss/${encodeURIComponent(vmssId)}/diagnostic-settings${qs}`;
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url, {
      method: 'GET',
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
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

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ vmssId: string }> }
): Promise<NextResponse> {
  const { vmssId } = await params;
  log.info('enable VMSS diagnostic settings', { vmssId: vmssId.slice(0, 40) });

  try {
    const { searchParams } = new URL(req.url);
    const query = searchParams.toString();
    const qs = query ? `?${query}` : '';
    const url = `${getApiGatewayUrl()}/api/v1/vmss/${encodeURIComponent(vmssId)}/diagnostic-settings${qs}`;
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    // Forward request body if present
    let body: string | undefined;
    const contentType = req.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
      body = await req.text();
    }

    const res = await fetch(url, {
      method: 'POST',
      headers: { ...upstreamHeaders, 'Content-Type': 'application/json' },
      body: body ?? undefined,
      signal: AbortSignal.timeout(60000),
    });

    const data = await res.json();
    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail });
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
