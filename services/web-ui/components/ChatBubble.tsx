'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ChatBubbleProps {
  agentName: string;
  content: string;
  isStreaming: boolean;
  timestamp: string;
}

export function ChatBubble({ agentName, content, isStreaming, timestamp }: ChatBubbleProps) {
  return (
    <div className="max-w-[95%] self-start rounded-xl border border-border bg-card shadow-sm mb-3 overflow-hidden">
      {/* Agent header — Azure accent strip for visual identity */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-accent border-b border-border">
        <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
        <span className="text-xs font-semibold text-accent-foreground tracking-wide">
          {agentName} Agent
        </span>
      </div>
      {/* Content */}
      <div className="px-3 py-2.5">
        <div className="chat-prose">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content}
          </ReactMarkdown>
          {isStreaming && (
            <span className="inline-block w-0.5 h-3.5 bg-primary ml-0.5 animate-blink-cursor" />
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-2">{timestamp}</p>
      </div>
    </div>
  );
}
