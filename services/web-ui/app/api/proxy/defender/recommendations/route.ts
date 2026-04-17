import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'
import { logger } from '@/lib/logger'

const log = logger.child({ route: '/api/proxy/defender/recommendations' })

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl()
    const { searchParams } = new URL(request.url)
    const query = searchParams.toString()
    log.info('proxy request', { method: 'GET', query })

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false)

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/defender/recommendations${query ? `?${query}` : ''}`,
      { headers: upstreamHeaders, signal: AbortSignal.timeout(15000) }
    )

    const data = await res.json()

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail })
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}`, recommendations: [], total: 0 },
        { status: res.status }
      )
    }

    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    log.error('gateway unreachable', { error: message })
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}`, recommendations: [], total: 0 },
      { status: 502 }
    )
  }
}
