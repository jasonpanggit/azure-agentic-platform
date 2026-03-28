'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

export interface SSEEvent {
  type: string;
  seq: number;
  data: Record<string, unknown>;
}

interface UseSSEOptions {
  threadId: string | null;
  streamType: 'token' | 'trace';
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Event) => void;
  onReconnect?: () => void;
  /** Increment to force a new SSE connection for the same threadId (e.g. each new message). */
  runKey?: number;
}

interface UseSSEResult {
  connected: boolean;
  reconnecting: boolean;
  lastSeq: number;
}

export function useSSE({
  threadId,
  streamType,
  onEvent,
  onError,
  onReconnect,
  runKey = 0,
}: UseSSEOptions): UseSSEResult {
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const lastSeqRef = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!threadId) return;

    // Close any existing connection before opening a new one
    eventSourceRef.current?.close();
    lastSeqRef.current = 0;

    const url = `/api/stream?thread_id=${encodeURIComponent(threadId)}&type=${streamType}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setReconnecting(false);
      onReconnect?.();
    };

    es.addEventListener(streamType, (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data) as SSEEvent;
        // Validate monotonic sequence
        if (parsed.seq > lastSeqRef.current) {
          lastSeqRef.current = parsed.seq;
          onEvent(parsed);
        }
      } catch {
        // Malformed event data — skip
      }
    });

    es.addEventListener('done', (event: MessageEvent) => {
      // Parse seq from done payload if available, otherwise use lastSeq + 1
      let seq = lastSeqRef.current + 1;
      try {
        const parsed = JSON.parse(event.data) as { seq?: number };
        if (parsed.seq) seq = parsed.seq;
      } catch { /* ignore */ }

      // Notify the component so it can clear isStreaming / finalize messages
      onEvent({ type: 'done', seq, data: { type: 'done' } });

      es.close();
      setConnected(false);
    });

    es.onerror = (err) => {
      setConnected(false);
      setReconnecting(true);
      onError?.(err);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, streamType, runKey, onEvent, onError, onReconnect]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return {
    connected,
    reconnecting,
    lastSeq: lastSeqRef.current,
  };
}
