import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/aks/[aksId]/monitoring' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/aks/[aksId]/monitoring
 *
 * Enables Container Insights on the AKS cluster by calling the API gateway which
 * in turn runs begin_create_or_update on the cluster.  This can take 2-3 minutes,
 * so the timeout is set to 3 minutes.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ aksId: string }> }
): Promise<NextResponse> {
  const { aksId } = await params;

  log.info('enable container insights', { aksId: aksId.slice(0, 40) });

  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/aks/${encodeURIComponent(aksId)}/monitoring`);

    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url.toString(), {
      method: 'POST',
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(180_000), // 3 min — begin_create_or_update is slow
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      log.warn('monitoring enable failed', { status: res.status, body: text.slice(0, 200) });
      return NextResponse.json({ success: false, error: `Upstream error ${res.status}` }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('monitoring proxy error', { error: message });
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
