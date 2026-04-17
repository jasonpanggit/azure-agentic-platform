import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/subscriptions' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/subscriptions
 *
 * Returns onboarded (managed) subscriptions from the API gateway's Cosmos-backed
 * subscription registry. This ensures the nav dropdown shows exactly the
 * subscriptions that have been onboarded with SPN credentials — not all ARM-visible
 * subscriptions.
 *
 * Previously this called ARM directly using DefaultAzureCredential, which returned
 * all subscriptions the web-ui MI had Reader on (not the onboarded set).
 */
export async function GET(req: NextRequest): Promise<NextResponse> {
  try {
    log.info('request start');

    const url = `${getApiGatewayUrl()}/api/v1/subscriptions/managed`;
    const upstreamHeaders = buildUpstreamHeaders(req.headers.get('Authorization'), false);

    const res = await fetch(url, {
      headers: upstreamHeaders,
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      const body = await res.text().catch(() => '');
      log.error('upstream error', { status: res.status, body });
      return NextResponse.json(
        { error: `managed subscriptions API error: ${res.status} ${body}`, subscriptions: [] },
        { status: res.status >= 500 ? 502 : res.status }
      );
    }

    const data = await res.json();

    // Map to { id, name } shape that SubscriptionSelector expects.
    // The managed endpoint returns { id, name, display_name, ... }
    const subscriptions: { id: string; name: string }[] = (data.subscriptions ?? []).map(
      (sub: { id?: string; name?: string; display_name?: string }) => ({
        id: sub.id ?? '',
        name: sub.display_name ?? sub.name ?? sub.id ?? '',
      })
    );

    subscriptions.sort((a, b) => a.name.localeCompare(b.name));

    log.debug('request success', { count: subscriptions.length });
    return NextResponse.json({ subscriptions });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    const isTimeout = message.includes('timeout') || message.includes('abort');
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, subscriptions: [] },
      { status: isTimeout ? 504 : 502 }
    );
  }
}
