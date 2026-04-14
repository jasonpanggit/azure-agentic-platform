import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/remediation-policies/[id]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse> {
  const { id } = await params;
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies/${id}`;
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Not found' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse> {
  const { id } = await params;
  try {
    const body = await req.json();
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies/${id}`;
    const res = await fetch(url, {
      method: 'PUT',
      headers: { ...buildUpstreamHeaders(req.headers.get('Authorization'), false), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }): Promise<NextResponse> {
  const { id } = await params;
  try {
    const url = `${getApiGatewayUrl()}/api/v1/admin/remediation-policies/${id}`;
    const res = await fetch(url, {
      method: 'DELETE',
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    });
    if (res.status === 204) return new NextResponse(null, { status: 204 });
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
