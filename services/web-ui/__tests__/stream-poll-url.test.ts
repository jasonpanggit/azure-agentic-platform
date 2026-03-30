/**
 * Tests: SSE stream route uses NEXT_PUBLIC_SITE_URL for internal polling.
 *
 * Key design note: GET(req) returns a Response immediately with a ReadableStream body.
 * The internal poll loop runs inside the stream's start() callback asynchronously.
 * We must drain the stream body to completion before asserting fetch calls.
 */
import { describe, it, expect, jest, beforeEach } from '@jest/globals';

async function drainStream(response: Response): Promise<string> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let output = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    output += decoder.decode(value);
  }
  return output;
}

describe('SSE stream route: internal poll URL', () => {
  beforeEach(() => {
    jest.resetModules();
    global.fetch = jest.fn() as any;
  });

  it('uses NEXT_PUBLIC_SITE_URL as base URL for internal poll', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://ca-web-ui-prod.example.azurecontainerapps.io';

    // Mock fetch to return a completed result — causes the polling loop to exit and close the stream
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        thread_id: 'th_123',
        run_status: 'completed',
        reply: 'Done',
      }),
    } as Response);

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_123&type=token');
    const req = new Request(url.toString());

    const response = await GET(req as any);
    expect(response.status).toBe(200);

    // Drain the stream to completion — ensures the internal poll loop fires
    await drainStream(response);

    // Verify the fetch was called with NEXT_PUBLIC_SITE_URL as base
    const fetchCalls = (global.fetch as jest.Mock).mock.calls;
    expect(fetchCalls.length).toBeGreaterThan(0);
    const pollUrl = fetchCalls[0][0] as string;
    expect(pollUrl).toContain('https://ca-web-ui-prod.example.azurecontainerapps.io/api/proxy/chat/result');
    expect(pollUrl).not.toContain('localhost:3000');
  });

  it('falls back to localhost:3000 when NEXT_PUBLIC_SITE_URL is not set', async () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ thread_id: 'th_123', run_status: 'completed', reply: 'Done' }),
    } as Response);

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_123&type=token');
    const req = new Request(url.toString());

    const response = await GET(req as any);
    await drainStream(response);

    const fetchCalls = (global.fetch as jest.Mock).mock.calls;
    expect(fetchCalls.length).toBeGreaterThan(0);
    const pollUrl = fetchCalls[0][0] as string;
    expect(pollUrl).toContain('http://localhost:3000/api/proxy/chat/result');
  });
});
