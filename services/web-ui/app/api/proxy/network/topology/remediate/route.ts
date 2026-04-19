import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'
import { logger } from '@/lib/logger'

const log = logger.child({ route: '/api/proxy/network/topology/remediate' })

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = await request.json()
    const upstream = `${getApiGatewayUrl()}/api/v1/network-topology/remediate`

    const res = await fetch(upstream, {
      method: 'POST',
      headers: buildUpstreamHeaders(request.headers.get('Authorization'), true),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    })

    const data = await res.json()

    if (!res.ok) {
      log.error('upstream error', { status: res.status, detail: data?.detail })
      return NextResponse.json(
        { status: 'error', message: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      )
    }

    log.info('remediation response', { status: data?.status, issue_id: body?.issue_id })
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unexpected error'
    log.error('gateway unreachable', { error: message })
    return NextResponse.json(
      { status: 'error', message: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    )
  }
}
