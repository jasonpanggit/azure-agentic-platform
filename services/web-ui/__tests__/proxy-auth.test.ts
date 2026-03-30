/**
 * Tests: proxy routes forward Authorization header to upstream gateway.
 */
import { describe, it, expect, jest, beforeEach } from '@jest/globals';

describe('Chat proxy: Authorization header pass-through', () => {
  const MOCK_GATEWAY = 'http://gateway-test:8000';

  beforeEach(() => {
    process.env.API_GATEWAY_URL = MOCK_GATEWAY;
    process.env.NEXT_PUBLIC_DEV_MODE = 'false';
    jest.resetModules();
    global.fetch = jest.fn() as any;
  });

  it('forwards Authorization header from incoming request to upstream fetch', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ thread_id: 'th_123', run_id: 'run_456', status: 'created' }),
    } as Response);

    const { POST } = await import('../app/api/proxy/chat/route');

    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer test-access-token',
      },
      body: JSON.stringify({ message: 'hello' }),
    });

    await POST(incomingRequest as any);

    expect(global.fetch).toHaveBeenCalledWith(
      `${MOCK_GATEWAY}/api/v1/chat`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-access-token',
        }),
      })
    );
  });

  it('makes upstream call without Authorization when header is absent (dev mode)', async () => {
    process.env.NEXT_PUBLIC_DEV_MODE = 'true';
    jest.resetModules();

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ thread_id: 'th_123', run_id: 'run_456', status: 'created' }),
    } as Response);

    const { POST } = await import('../app/api/proxy/chat/route');

    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    });

    const response = await POST(incomingRequest as any);
    expect(response.status).toBe(200);
    const fetchCall = (global.fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    const headers = fetchCall.headers as Record<string, string>;
    expect(headers['Authorization']).toBeUndefined();
  });
});

describe('Chat proxy: API_GATEWAY_URL validation', () => {
  beforeEach(() => {
    global.fetch = jest.fn() as any;
    delete process.env.API_GATEWAY_URL;
    process.env.NEXT_PUBLIC_DEV_MODE = 'false';
    jest.resetModules();
  });

  it('returns 502 when API_GATEWAY_URL is unset and not in dev mode', async () => {
    const { POST } = await import('../app/api/proxy/chat/route');

    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    });

    const response = await POST(incomingRequest as any);
    // 502 because the throw is caught by the proxy's try/catch (gateway error, not server error)
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error).toContain('API_GATEWAY_URL is not configured');
  });

  it('defaults to localhost:8000 in dev mode when API_GATEWAY_URL unset', async () => {
    process.env.NEXT_PUBLIC_DEV_MODE = 'true';
    jest.resetModules();

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ thread_id: 'th_123' }),
    } as Response);

    const { POST } = await import('../app/api/proxy/chat/route');
    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    });

    await POST(incomingRequest as any);

    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/chat',
      expect.anything()
    );
  });
});
