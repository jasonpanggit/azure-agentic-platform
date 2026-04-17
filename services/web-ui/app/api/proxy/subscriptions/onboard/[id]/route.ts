import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  try {
    const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${id}`, {
      method: 'DELETE',
      headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
      signal: AbortSignal.timeout(15000),
    })
    const data = await resp.json().catch(() => ({ error: `Gateway error: ${resp.status}` }))
    return Response.json(data, { status: resp.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return Response.json({ error: `Failed to reach API gateway: ${message}` }, { status: 502 })
  }
}
