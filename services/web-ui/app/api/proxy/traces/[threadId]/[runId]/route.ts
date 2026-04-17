import { NextRequest, NextResponse } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'
import { logger } from '@/lib/logger'

const log = logger.child({ route: '/api/proxy/traces/[threadId]/[runId]' })

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface Params {
  params: Promise<{ threadId: string; runId: string }>
}

/**
 * GET /api/proxy/traces/[threadId]/[runId]
 *
 * Proxies a single trace detail request to the API gateway.
 */
export async function GET(request: NextRequest, { params }: Params): Promise<NextResponse> {
  const { threadId, runId } = await params
  try {
    const apiGatewayUrl = getApiGatewayUrl()
    log.info('proxy request', { method: 'GET', threadId, runId })

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false)

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/traces/${encodeURIComponent(threadId)}/${encodeURIComponent(runId)}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(10000),
      }
    )

    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    log.error('proxy error', { err, threadId, runId })
    return NextResponse.json({ error: 'Failed to fetch trace' }, { status: 502 })
  }
}
