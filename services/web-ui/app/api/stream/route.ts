import { NextRequest } from 'next/server';
import { globalEventBuffer } from '@/lib/sse-buffer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const HEARTBEAT_INTERVAL_MS = 20_000; // 20 seconds (UI-008)
const POLL_INTERVAL_MS = 2_000;       // Poll Foundry run status every 2 seconds
const POLL_TIMEOUT_MS = 120_000;      // Give up after 2 minutes
// 'not_found' is intentionally excluded — the run may not be visible in Foundry
// immediately after creation (propagation delay). Keep polling until timeout.
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'expired']);

interface RunResultPayload {
  thread_id: string;
  run_status: string;
  reply?: string | null;
}

/**
 * SSE Route Handler — polls Foundry for run completion and emits events.
 *
 * Query params:
 *   thread_id: Foundry thread ID
 *   type: 'token' | 'trace' (which event stream)
 *
 * Events emitted:
 *   event: token — data: {"delta":"...", "seq": N, "agent": "orchestrator"}
 *   event: done  — data: {"seq": N}
 *   : heartbeat (SSE comment, every 20s)
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const threadId = searchParams.get('thread_id');
  const streamType = searchParams.get('type') || 'token';
  const runId = searchParams.get('run_id');

  if (!threadId) {
    return new Response('Missing thread_id parameter', { status: 400 });
  }

  let seq = 0;
  const lastEventId = request.headers.get('Last-Event-ID');
  const lastSeqParam = searchParams.get('last_seq');
  const startSeq = lastEventId
    ? parseInt(lastEventId, 10)
    : lastSeqParam ? parseInt(lastSeqParam, 10) : 0;

  const encoder = new TextEncoder();
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let aborted = false;

  const pushEvent = (
    controller: ReadableStreamDefaultController,
    eventName: string,
    data: Record<string, unknown>
  ) => {
    seq++;
    const payload = { ...data, seq };
    const sseMessage = `id: ${seq}\nevent: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`;
    controller.enqueue(encoder.encode(sseMessage));
    globalEventBuffer.push(threadId, {
      id: String(seq),
      seq,
      event: eventName,
      data: JSON.stringify(payload),
      timestamp: Date.now(),
    });
  };

  const stream = new ReadableStream({
    async start(controller) {
      // Replay missed events from ring buffer on reconnect (only if client has seen prior events)
      if (startSeq > 0) {
        const missed = globalEventBuffer.getEventsSince(threadId, startSeq);
        for (const event of missed) {
          controller.enqueue(
            encoder.encode(`id: ${event.id}\nevent: ${event.event}\ndata: ${event.data}\n\n`)
          );
          seq = event.seq;
        }
      }

      // Heartbeat to keep the SSE connection alive through proxies (UI-008)
      heartbeatTimer = setInterval(() => {
        if (!aborted) {
          try {
            controller.enqueue(encoder.encode(': heartbeat\n\n'));
          } catch {
            // Controller already closed
          }
        }
      }, HEARTBEAT_INTERVAL_MS);

      request.signal.addEventListener('abort', () => {
        aborted = true;
        if (heartbeatTimer) clearInterval(heartbeatTimer);
        try { controller.close(); } catch { /* already closed */ }
      });

      // Only the token stream polls Foundry — trace stream stays open for future use
      if (streamType !== 'token') {
        return;
      }

      // Poll the API gateway for run completion
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      const runIdParam = runId ? `&run_id=${encodeURIComponent(runId)}` : '';
      // Allow up to 5 consecutive not_found responses (~10s) before treating as terminal.
      // This absorbs Foundry's ~1-2s propagation delay without polling forever on genuinely missing runs.
      const NOT_FOUND_LIMIT = 5;
      let notFoundCount = 0;

      while (!aborted && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        if (aborted) break;

        try {
          const res = await fetch(
            `http://localhost:3000/api/proxy/chat/result?thread_id=${encodeURIComponent(threadId)}${runIdParam}`,
            { signal: AbortSignal.timeout(8000) }
          );

          if (!res.ok) continue; // transient error — keep polling

          const result = (await res.json()) as RunResultPayload;

          if (result.run_status === 'not_found') {
            notFoundCount++;
            if (notFoundCount < NOT_FOUND_LIMIT) continue; // transient — keep polling
            // Exceeded limit: treat as terminal
          } else {
            notFoundCount = 0; // reset on any other status
          }

          if (!TERMINAL_STATUSES.has(result.run_status) && result.run_status !== 'not_found') continue; // still running

          if (result.run_status === 'completed' && result.reply) {
            pushEvent(controller, 'token', {
              type: 'token',
              delta: result.reply,
              agent: 'orchestrator',
            });
          } else if (result.run_status !== 'completed') {
            pushEvent(controller, 'token', {
              type: 'token',
              delta: `Agent run ended with status: ${result.run_status}`,
              agent: 'orchestrator',
            });
          }

          // Emit done and close
          pushEvent(controller, 'done', { type: 'done' });
          break;
        } catch {
          // Network error during poll — continue
        }
      }

      // Timeout — emit a friendly done so the spinner clears
      if (!aborted && Date.now() >= deadline) {
        pushEvent(controller, 'token', {
          type: 'token',
          delta: 'Agent response timed out. Please try again.',
          agent: 'orchestrator',
        });
        pushEvent(controller, 'done', { type: 'done' });
      }

      if (heartbeatTimer) clearInterval(heartbeatTimer);
      try { controller.close(); } catch { /* already closed */ }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}

