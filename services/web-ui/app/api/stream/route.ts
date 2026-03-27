import { NextRequest } from 'next/server';
import { globalEventBuffer } from '@/lib/sse-buffer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const HEARTBEAT_INTERVAL_MS = 20_000; // 20 seconds (UI-008)
const API_GATEWAY_URL = process.env.API_GATEWAY_URL || 'http://localhost:8000';

/**
 * SSE Route Handler — proxies Foundry thread events to the browser.
 *
 * Query params:
 *   thread_id: Foundry thread ID
 *   type: 'token' | 'trace' (which event stream)
 *
 * Headers:
 *   Last-Event-ID: Sequence number for reconnection replay
 *   Authorization: Bearer token (proxied to api-gateway)
 *
 * Events emitted:
 *   event: token — data: {"delta":"...", "seq": N, "agent": "compute"}
 *   event: trace — data: {"type":"tool_call", "seq": N, ...}
 *                  data: {"type":"approval_gate", "approval_id": "...", "seq": N, ...}
 *   event: done  — data: {"seq": N}
 *   : heartbeat (SSE comment, every 20s)
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const threadId = searchParams.get('thread_id');
  const streamType = searchParams.get('type') || 'token'; // 'token' or 'trace'

  if (!threadId) {
    return new Response('Missing thread_id parameter', { status: 400 });
  }

  let seq = 0;
  const lastEventId = request.headers.get('Last-Event-ID');
  const startSeq = lastEventId ? parseInt(lastEventId, 10) : 0;

  const encoder = new TextEncoder();
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let aborted = false;

  const stream = new ReadableStream({
    async start(controller) {
      // Replay missed events from ring buffer on reconnect
      if (startSeq > 0) {
        const missed = globalEventBuffer.getEventsSince(threadId, startSeq);
        for (const event of missed) {
          const sseMessage = `id: ${event.id}\nevent: ${event.event}\ndata: ${event.data}\n\n`;
          controller.enqueue(encoder.encode(sseMessage));
          seq = event.seq;
        }
      }

      // Start heartbeat timer (UI-008)
      heartbeatTimer = setInterval(() => {
        if (!aborted) {
          try {
            controller.enqueue(encoder.encode(': heartbeat\n\n'));
          } catch {
            // Controller closed
          }
        }
      }, HEARTBEAT_INTERVAL_MS);

      // Listen for client disconnect
      request.signal.addEventListener('abort', () => {
        aborted = true;
        if (heartbeatTimer) clearInterval(heartbeatTimer);
        try {
          controller.close();
        } catch {
          // Already closed
        }
      });

      // TODO: Connect to Foundry thread streaming via api-gateway
      // For now, emit a synthetic "connected" event
      seq++;
      const connectedEvent = {
        type: 'connected',
        seq,
        thread_id: threadId,
        stream_type: streamType,
      };
      const eventStr = `id: ${seq}\nevent: ${streamType}\ndata: ${JSON.stringify(connectedEvent)}\n\n`;
      controller.enqueue(encoder.encode(eventStr));

      globalEventBuffer.push(threadId, {
        id: String(seq),
        seq,
        event: streamType,
        data: JSON.stringify(connectedEvent),
        timestamp: Date.now(),
      });
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
