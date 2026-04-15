import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/compliance/export' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/proxy/compliance/export
 *
 * Proxies compliance export requests to the API gateway.
 * Passes through binary/text content directly (CSV or PDF).
 *
 * Query params: subscription_id, format (csv|pdf), framework (optional)
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const { searchParams } = new URL(request.url);
    const query = searchParams.toString();
    const format = searchParams.get('format') ?? 'csv';
    log.info('proxy request', { method: 'GET', format, query });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'), false);

    const res = await fetch(
      `${apiGatewayUrl}/api/v1/compliance/export${query ? `?${query}` : ''}`,
      {
        headers: upstreamHeaders,
        signal: AbortSignal.timeout(30000), // PDF generation may take longer
      }
    );

    if (!res.ok) {
      const errorText = await res.text().catch(() => 'Unknown error');
      log.error('upstream error', { status: res.status, detail: errorText });
      return NextResponse.json(
        { error: `Export failed: ${errorText}` },
        { status: res.status }
      );
    }

    // Pass through binary/text response with correct Content-Type and Content-Disposition
    const contentType = res.headers.get('content-type') ?? 'application/octet-stream';
    const contentDisposition = res.headers.get('content-disposition') ?? '';
    const body = await res.arrayBuffer();

    return new NextResponse(body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        ...(contentDisposition ? { 'Content-Disposition': contentDisposition } : {}),
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
