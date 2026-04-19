import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * GET /api/proxy/firewall/audit
 *
 * Proxies to GET /api/v1/firewall/audit on the API gateway.
 * Query params forwarded: subscription_ids, severity
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams } = new URL(request.url)
  const url = new URL(`${getApiGatewayUrl()}/api/v1/firewall/audit`)
  const subscriptionIds = searchParams.get('subscription_ids')
  const severity = searchParams.get('severity')
  if (subscriptionIds) url.searchParams.set('subscription_ids', subscriptionIds)
  if (severity) url.searchParams.set('severity', severity)

  try {
    const res = await fetch(url.toString(), {
      headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return NextResponse.json({ error: message }, { status: 502 })
  }
}
