import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest): Promise<NextResponse> {
  try {
    const url = `${getApiGatewayUrl()}/api/v1/nsg/findings/summary`
    const res = await fetch(url, {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    })

    if (!res.ok) {
      return NextResponse.json(
        {
          counts: { critical: 0, high: 0, medium: 0, info: 0, total: 0 },
          top_risky_nsgs: [],
          generated_at: new Date().toISOString(),
          error: `upstream ${res.status}`,
        },
        { status: res.status },
      )
    }
    return NextResponse.json(await res.json())
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'unknown error'
    return NextResponse.json(
      {
        counts: { critical: 0, high: 0, medium: 0, info: 0, total: 0 },
        top_risky_nsgs: [],
        generated_at: new Date().toISOString(),
        error: message,
      },
      { status: 503 },
    )
  }
}
