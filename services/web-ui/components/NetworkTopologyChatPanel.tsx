'use client';

import { useRef, useEffect } from 'react';
import { X, Send, MessageSquare, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  useNetworkChat,
  type TopologyContext,
  type ChatMessage,
} from '@/lib/use-network-chat';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NetworkTopologyChatPanelProps {
  subscriptionIds: string[];
  topologyContext: TopologyContext;
  nodeIndex: Map<string, string>;
  onHighlight: (nodeIds: Set<string>) => void;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Quick-start prompts
// ---------------------------------------------------------------------------

const QUICK_PROMPTS = [
  'List all VNets',
  'Which NSGs have open inbound rules?',
  'Show subnets without NSGs',
  'Describe VNet peering topology',
];

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div
        className="rounded-lg px-3 py-2 text-sm max-w-[85%] whitespace-pre-wrap break-words"
        style={
          isUser
            ? {
                background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                color: 'var(--text-primary)',
                border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)',
              }
            : {
                background: 'var(--bg-subtle)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)',
              }
        }
      >
        {msg.content || (
          <span style={{ color: 'var(--text-muted)' }}>
            <Loader2 size={12} className="animate-spin inline mr-1" />
            Thinking…
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export default function NetworkTopologyChatPanel({
  subscriptionIds,
  topologyContext,
  nodeIndex,
  onHighlight,
  onClose,
}: NetworkTopologyChatPanelProps) {
  const { messages, input, setInput, isStreaming, sendMessage } = useNetworkChat({
    subscriptionIds,
    topologyContext,
    onHighlight,
    nodeIndex,
  });

  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleQuickPrompt = (prompt: string) => {
    setInput(prompt);
  };

  return (
    <div
      className="flex flex-col h-full"
      style={{
        background: 'var(--bg-canvas)',
        borderLeft: '1px solid var(--border)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <MessageSquare size={14} style={{ color: 'var(--accent-blue)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Ask AI
          </span>
          <span
            className="text-[10px] px-1.5 py-px rounded-full"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
              color: 'var(--accent-blue)',
            }}
          >
            Network Agent
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 hover:opacity-70 transition-opacity"
          aria-label="Close chat"
          style={{ color: 'var(--text-muted)' }}
        >
          <X size={14} />
        </button>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 ? (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-center" style={{ color: 'var(--text-muted)' }}>
              Ask questions about the network topology. Matching resources will be highlighted on the map.
            </p>
            <div className="flex flex-col gap-2 mt-2">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => handleQuickPrompt(prompt)}
                  className="text-left text-xs rounded-lg px-3 py-2 transition-opacity hover:opacity-80"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-blue) 8%, transparent)',
                    border: '1px solid color-mix(in srgb, var(--accent-blue) 20%, transparent)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div
        className="shrink-0 px-4 py-3 flex flex-col gap-2"
        style={{ borderTop: '1px solid var(--border)' }}
      >
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about VNets, NSGs, peerings…"
          rows={2}
          className="resize-none text-sm"
          style={{
            background: 'var(--bg-surface)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
          }}
          disabled={isStreaming}
        />
        <Button
          size="sm"
          onClick={sendMessage}
          disabled={!input.trim() || isStreaming}
          className="self-end"
        >
          {isStreaming ? (
            <Loader2 size={12} className="animate-spin mr-1" />
          ) : (
            <Send size={12} className="mr-1" />
          )}
          {isStreaming ? 'Thinking…' : 'Send'}
        </Button>
      </div>
    </div>
  );
}
