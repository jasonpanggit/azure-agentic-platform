'use client';

import React from 'react';

interface UserBubbleProps {
  content: string;
  timestamp: string;
}

export function UserBubble({ content, timestamp }: UserBubbleProps) {
  return (
    <div className="max-w-[85%] self-end rounded-lg bg-primary text-primary-foreground p-3 mb-2 shadow-sm">
      <p className="text-sm">{content}</p>
      <p className="text-xs opacity-70 mt-1">{timestamp}</p>
    </div>
  );
}
