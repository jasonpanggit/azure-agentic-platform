import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/runbooks/[id]/execute' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/runbooks/[id]/execute
 *
 * Streams SSE step results from the API gateway runbook executor.
 * Forwards dry_run query param when present.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } }
): Promise<NextResponse> {
  const { id } = params;
  const dryRun = req.nextUrl.searchParams.get('dry_run') ?? 'false';

  log.info('proxy request', { method: 'POST', runbook_id: id, dry_run: dryRun });

  try {
    const body = await req.text();
    const url = new URL(`${getApiGatewayUrl()}/api/v1/runbooks/${encodeURIComponent(id)}/execute`);
    url.searchParams.set('dry_run', dryRun);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      method: 'POST',
      headers: { ...upstreamHeaders, 'Content-Type': 'application/json' },
      body: body || '{}',
      signal: AbortSignal.timeout(120000),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      log.error('runbook execute upstream error', { status: res.status, runbook_id: id });
      return NextResponse.json(
        { error: data?.detail ?? data?.error ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    // Stream SSE through
    return new NextResponse(res.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable for runbook execute', { error: message, runbook_id: id });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
