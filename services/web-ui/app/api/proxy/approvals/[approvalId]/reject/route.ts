import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL ||
  'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ approvalId: string }> }
): Promise<NextResponse> {
  try {
    const { approvalId } = await params;
    const body = await request.json();

    const res = await fetch(
      `${API_GATEWAY_URL}/api/v1/approvals/${approvalId}/reject`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      }
    );

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
