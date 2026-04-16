import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/tenants' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'GET' });
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/tenants`;
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail ?? 'Gateway error' }, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  log.info('proxy request', { method: 'POST' });
  try {
    const body = await req.json();
    const url = `${getApiGatewayUrl()}/api/v1/admin/tenants`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        ...buildUpstreamHeaders(req.headers.get('Authorization'), false),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail ?? 'Gateway error' }, { status: res.status });
    }
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 });
  }
}
