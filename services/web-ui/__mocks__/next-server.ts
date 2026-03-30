/**
 * Minimal mock for next/server — provides NextRequest and NextResponse
 * in a plain Node.js test environment without requiring the full Next.js runtime.
 */

export class NextResponse extends Response {
  static json(data: unknown, init?: ResponseInit): NextResponse {
    const body = JSON.stringify(data);
    const headers = new Headers(init?.headers);
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    return new NextResponse(body, { ...init, headers });
  }
}

export class NextRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(input, init);
  }
}
