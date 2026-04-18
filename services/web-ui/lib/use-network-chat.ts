'use client';

import { useState, useRef, useCallback } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface TopologyContext {
  nodeCount: number;
  edgeCount: number;
  selectedNodeId?: string;
}

export interface UseNetworkChatOptions {
  subscriptionIds: string[];
  topologyContext: TopologyContext;
  /** Called after each complete assistant reply with the set of matched node IDs. */
  onHighlight: (nodeIds: Set<string>) => void;
  /** Maps resource ID (lowercased) and short name (lowercased) → node ID. */
  nodeIndex: Map<string, string>;
}

export interface UseNetworkChatResult {
  messages: ChatMessage[];
  input: string;
  setInput: (v: string) => void;
  isStreaming: boolean;
  sendMessage: () => void;
  threadId: string | null;
}

// ---------------------------------------------------------------------------
// Resource reference extraction
// ---------------------------------------------------------------------------

/**
 * Pure helper: scans agent reply text for Azure ARM resource IDs
 * (/subscriptions/…/providers/…) and short names, matching against nodeIndex.
 *
 * Returns a Set of matched node IDs.
 */
export function extractResourceRefs(
  text: string,
  nodeIndex: Map<string, string>
): Set<string> {
  const matched = new Set<string>();
  const lower = text.toLowerCase();

  // Pass 1: full ARM resource ID patterns
  const armPattern = /\/subscriptions\/[0-9a-f-]{36}\/[^\s"',)]+/gi;
  let m: RegExpExecArray | null;
  while ((m = armPattern.exec(text)) !== null) {
    const key = m[0].toLowerCase();
    const nodeId = nodeIndex.get(key);
    if (nodeId) matched.add(nodeId);
  }

  // Pass 2: short names (every token from nodeIndex that appears in the reply)
  for (const [key, nodeId] of nodeIndex.entries()) {
    // Skip very short keys (≤3 chars) to avoid false positives
    if (key.length <= 3) continue;
    if (lower.includes(key)) {
      matched.add(nodeId);
    }
  }

  return matched;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useNetworkChat(opts: UseNetworkChatOptions): UseNetworkChatResult {
  const { subscriptionIds, topologyContext, onHighlight, nodeIndex } = opts;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const threadIdRef = useRef<string | null>(null);

  const sendMessage = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput('');

    // Clear previous highlights
    onHighlight(new Set());

    // Append user bubble immediately
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
    };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    // Start SSE stream
    (async () => {
      let accumulatedReply = '';
      try {
        const res = await fetch('/api/proxy/network/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            subscription_ids: subscriptionIds,
            thread_id: threadIdRef.current ?? undefined,
            topology_context: {
              node_count: topologyContext.nodeCount,
              edge_count: topologyContext.edgeCount,
              selected_node_id: topologyContext.selectedNodeId,
            },
          }),
        });

        if (!res.body) throw new Error('No response body');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice('data: '.length).trim();
            if (payload === '[DONE]') break;

            try {
              const parsed = JSON.parse(payload) as { token?: string; error?: string; thread_id?: string };
              if (parsed.thread_id && !threadIdRef.current) {
                threadIdRef.current = parsed.thread_id;
              }
              if (parsed.error) {
                accumulatedReply += `\n\n[Error: ${parsed.error}]`;
              } else if (parsed.token) {
                accumulatedReply += parsed.token;
              }
            } catch {
              // Non-JSON line — skip
            }

            // Update assistant bubble incrementally
            const snapshot = accumulatedReply;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId ? { ...msg, content: snapshot } : msg
              )
            );
          }
        }
      } catch (err) {
        const errorText = err instanceof Error ? err.message : 'Unknown error';
        accumulatedReply += `\n\n[Error: ${errorText}]`;
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, content: accumulatedReply }
              : msg
          )
        );
      } finally {
        setIsStreaming(false);
        // Extract resource references and highlight matching nodes
        const matched = extractResourceRefs(accumulatedReply, nodeIndex);
        onHighlight(matched);
      }
    })();
  }, [input, isStreaming, subscriptionIds, topologyContext, onHighlight, nodeIndex]);

  return {
    messages,
    input,
    setInput,
    isStreaming,
    sendMessage,
    threadId: threadIdRef.current,
  };
}
