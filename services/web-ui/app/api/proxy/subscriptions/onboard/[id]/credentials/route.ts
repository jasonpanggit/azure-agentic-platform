import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await request.text()
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${id}/credentials`, {
    method: 'PUT',
    headers: buildUpstreamHeaders(request.headers.get('Authorization'), true),
    body,
    signal: AbortSignal.timeout(30000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
