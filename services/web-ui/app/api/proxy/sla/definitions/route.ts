import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest): Promise<NextResponse> {
  try {
    const url = new URL(`${getApiGatewayUrl()}/api/v1/admin/sla-definitions`)
    const searchParams = req.nextUrl.searchParams
    const includeInactive = searchParams.get('include_inactive')
    if (includeInactive) url.searchParams.set('include_inactive', includeInactive)

    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(req.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) {
      return NextResponse.json(
        { items: [], total: 0, error: `upstream ${res.status}` },
        { status: res.status },
      )
    }
    return NextResponse.json(await res.json())
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error'
    return NextResponse.json({ items: [], total: 0, error: message }, { status: 503 })
  }
}
