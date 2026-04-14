import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/admin/policy-suggestions/[id]/[action]' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; action: string }> }
): Promise<NextResponse> {
  const { id, action } = await params;
  if (!['dismiss', 'convert'].includes(action)) {
    return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
  }
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/admin/policy-suggestions/${id}/${action}`);
    // Forward query params (e.g. action_class for dismiss)
    req.nextUrl.searchParams.forEach((value, key) => url.searchParams.set(key, value));
    const bodyText = await req.text();
    const fetchOpts: RequestInit = {
      method: 'POST',
      headers: { ...buildUpstreamHeaders(req.headers.get('Authorization'), false), 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(15000),
    };
    if (bodyText) fetchOpts.body = bodyText;
    const res = await fetch(url.toString(), fetchOpts);
    const data = await res.json();
    if (!res.ok) return NextResponse.json({ error: data?.detail ?? 'Error' }, { status: res.status });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
