import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${id}/validate`, {
    method: 'POST',
    headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
    signal: AbortSignal.timeout(30000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
