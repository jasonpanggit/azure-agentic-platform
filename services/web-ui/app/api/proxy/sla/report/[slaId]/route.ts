import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ slaId: string }> },
): Promise<NextResponse> {
  const { slaId } = await params
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/sla/report/${slaId}`)
    const res = await fetch(url.toString(), {
      method: 'POST',
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(60000),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      return NextResponse.json(
        { error: (body as { detail?: string })?.detail ?? `upstream ${res.status}` },
        { status: res.status },
      )
    }
    return NextResponse.json(await res.json())
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error'
    return NextResponse.json({ error: message }, { status: 503 })
  }
}
