import { NextRequest } from 'next/server'
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway'

export async function DELETE(request: NextRequest, { params }: { params: { id: string } }) {
  const resp = await fetch(`${getApiGatewayUrl()}/api/v1/subscriptions/onboard/${params.id}`, {
    method: 'DELETE',
    headers: buildUpstreamHeaders(request.headers.get('Authorization'), false),
    signal: AbortSignal.timeout(15000),
  })
  return Response.json(await resp.json(), { status: resp.status })
}
