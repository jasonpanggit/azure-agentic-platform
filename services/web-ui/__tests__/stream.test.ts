/**
 * Tests for SSE stream route heartbeat behavior (UI-008).
 *
 * Tests the heartbeat emitted in services/web-ui/app/api/stream/route.ts.
 * Uses Jest fake timers to avoid 20-second real waits.
 *
 * Drain strategy: After jest.advanceTimersByTimeAsync(21_000), the heartbeat
 * chunk is already enqueued synchronously in the ReadableStream buffer.
 * Call reader.read() directly — no Promise.race or setTimeout drain needed
 * (those would hang with fake timers active).
 *
 * Note: The polling loop uses setTimeout(resolve, 2000) before each fetch.
 * Advancing 21s drives ~10 poll iterations (all returning in_progress) AND
 * fires the 20s heartbeat interval. The stream stays open; we cancel after
 * reading the heartbeat chunk.
 */
import { describe, it, expect, jest, beforeEach, afterEach } from '@jest/globals';

describe('SSE stream route: heartbeat (UI-008)', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.resetModules();
    global.fetch = jest.fn() as any;
    // Mock fetch to return in_progress — keeps the polling loop alive
    // so the stream stays open long enough to observe the heartbeat.
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ thread_id: 'th_123', run_status: 'in_progress', reply: null }),
    } as Response);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('emits ": heartbeat" SSE comment after 20-second interval fires', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'http://localhost:3000';

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_123&type=token');
    const req = new Request(url.toString());
    const response = await GET(req as any);

    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/event-stream');
    expect(response.body).not.toBeNull();

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();

    // Advance fake time by 21 seconds:
    //   - fires setInterval callback at t=20s → enqueues ': heartbeat\n\n'
    //   - fires poll-loop setTimeout(2000) ~10 times (each fetch returns in_progress,
    //     so the loop does not close the stream)
    await jest.advanceTimersByTimeAsync(21_000);

    // Heartbeat chunk is now in the stream buffer — read() resolves immediately
    const firstRead = await reader.read();
    const output = firstRead.value ? decoder.decode(firstRead.value) : '';

    expect(output).toContain(': heartbeat');

    await reader.cancel();
  });

  it('response has correct SSE Content-Type and Cache-Control headers', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'http://localhost:3000';

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_abc&type=token');
    const req = new Request(url.toString());
    const response = await GET(req as any);

    expect(response.headers.get('Content-Type')).toBe('text/event-stream');
    expect(response.headers.get('Cache-Control')).toContain('no-cache');

    await response.body!.cancel();
  });

  it('returns 400 when thread_id is missing', async () => {
    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?type=token');
    const req = new Request(url.toString());
    const response = await GET(req as any);

    expect(response.status).toBe(400);
  });
});
