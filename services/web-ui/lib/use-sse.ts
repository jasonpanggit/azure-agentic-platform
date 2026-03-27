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
}: UseSSEOptions): UseSSEResult {
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const lastSeqRef = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!threadId) return;

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
        // Ignore duplicate or out-of-order events
      } catch {
        // Malformed event data — skip
      }
    });

    es.addEventListener('done', () => {
      es.close();
      setConnected(false);
    });

    es.onerror = (err) => {
      setConnected(false);
      setReconnecting(true);
      onError?.(err);
      // EventSource auto-reconnects with Last-Event-ID
    };
  }, [threadId, streamType, onEvent, onError, onReconnect]);

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
