/**
 * In-memory ring buffer for SSE event replay on reconnect.
 *
 * Specification:
 * - Max 1000 events per thread (configurable)
 * - Keyed by thread_id in a Map
 * - Events evicted on thread completion or after 30-min TTL
 * - On reconnect: scan buffer for events with seq > Last-Event-ID, replay in order
 */

interface BufferedEvent {
  id: string;      // Sequence number as string
  seq: number;
  event: string;   // 'token' | 'trace' | 'done' | 'error'
  data: string;    // JSON-serialized data
  timestamp: number; // Date.now() at buffer time
}

const DEFAULT_MAX_SIZE = 1000;
const DEFAULT_TTL_MS = 30 * 60 * 1000; // 30 minutes

export class SSEEventBuffer {
  private buffers: Map<string, BufferedEvent[]> = new Map();
  private maxSize: number;
  private ttlMs: number;

  constructor(maxSize = DEFAULT_MAX_SIZE, ttlMs = DEFAULT_TTL_MS) {
    this.maxSize = maxSize;
    this.ttlMs = ttlMs;
  }

  /**
   * Add an event to the buffer for a thread.
   */
  push(threadId: string, event: BufferedEvent): void {
    if (!this.buffers.has(threadId)) {
      this.buffers.set(threadId, []);
    }
    const buffer = this.buffers.get(threadId)!;
    buffer.push(event);

    // Evict oldest if over capacity
    if (buffer.length > this.maxSize) {
      buffer.shift();
    }
  }

  /**
   * Get all events since (exclusive) the given sequence number.
   * Returns events with seq > sinceSeq, in order.
   */
  getEventsSince(threadId: string, sinceSeq: number): BufferedEvent[] {
    const buffer = this.buffers.get(threadId);
    if (!buffer) return [];

    const now = Date.now();
    return buffer.filter(
      (e) => e.seq > sinceSeq && (now - e.timestamp) < this.ttlMs
    );
  }

  /**
   * Remove all events for a thread (on completion or TTL).
   */
  clear(threadId: string): void {
    this.buffers.delete(threadId);
  }

  /**
   * Get the current buffer size for a thread.
   */
  size(threadId: string): number {
    return this.buffers.get(threadId)?.length ?? 0;
  }
}

// Singleton buffer instance
export const globalEventBuffer = new SSEEventBuffer();
