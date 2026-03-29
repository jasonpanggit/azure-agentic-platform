'use client';

import React from 'react';

interface ThinkingIndicatorProps {
  agentName: string;
}

export function ThinkingIndicator({ agentName }: ThinkingIndicatorProps) {
  return (
    <div className="flex items-center gap-2 px-4 py-2">
      <div className="flex gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse-dot" />
        <span
          className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse-dot"
          style={{ animationDelay: '0.2s' }}
        />
        <span
          className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse-dot"
          style={{ animationDelay: '0.4s' }}
        />
      </div>
      <span className="text-sm text-muted-foreground">
        {agentName} Agent is analyzing...
      </span>
    </div>
  );
}
