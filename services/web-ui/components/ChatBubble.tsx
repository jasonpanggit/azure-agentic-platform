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
    <div className="max-w-[95%] self-start rounded-lg border bg-card p-3 mb-2 shadow-sm">
      <div className="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary mb-1.5">
        {agentName} Agent
      </div>
      <div className="prose prose-sm prose-zinc max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {content}
        </ReactMarkdown>
        {isStreaming && (
          <span className="inline-block w-0.5 h-3.5 bg-foreground ml-0.5 animate-blink-cursor" />
        )}
      </div>
      <p className="text-xs text-muted-foreground mt-1">{timestamp}</p>
    </div>
  );
}
