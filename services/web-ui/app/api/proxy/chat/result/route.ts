import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';

/**
 * GET /api/proxy/chat/result?thread_id=<id>
 *
 * Polls the API gateway for the Foundry run status on a given thread.
 * Returns: { thread_id, run_status, reply? }
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const threadId = searchParams.get('thread_id');
  const runId = searchParams.get('run_id');

  if (!threadId) {
    return NextResponse.json({ error: 'Missing thread_id parameter' }, { status: 400 });
  }

  try {
    const runIdParam = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    const res = await fetch(
      `${API_GATEWAY_URL}/api/v1/chat/${encodeURIComponent(threadId)}/result${runIdParam}`,
      {
        headers: {
          'Content-Type': 'application/json',
        },
        signal: AbortSignal.timeout(10000),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
