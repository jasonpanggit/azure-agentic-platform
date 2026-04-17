import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'
import { logger } from '@/lib/logger'

const log = logger.child({ route: '/api/proxy/traces' })

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * GET /api/proxy/traces
 *
 * Proxies trace list requests to the API gateway.
 * Query params forwarded as-is (thread_id, incident_id, limit, offset).
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl()
    const { searchParams } = new URL(request.url)
    const query = searchParams.toString()
    log.info('proxy request', { method: 'GET', query })

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false)

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/traces${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(15000),
      }
    )

    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    log.error('proxy error', { err })
    return NextResponse.json({ error: 'Failed to fetch traces' }, { status: 502 })
  }
}
