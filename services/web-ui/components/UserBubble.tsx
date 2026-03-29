'use client';

import React from 'react';

interface UserBubbleProps {
  content: string;
  timestamp: string;
}

export function UserBubble({ content, timestamp }: UserBubbleProps) {
  return (
    <div className="max-w-[85%] self-end rounded-xl bg-primary text-primary-foreground px-3 py-2.5 mb-3 shadow-sm">
      <p className="text-sm leading-relaxed">{content}</p>
      <p className="text-xs opacity-60 mt-1.5">{timestamp}</p>
    </div>
  );
}
