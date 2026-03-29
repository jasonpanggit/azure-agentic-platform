'use client';

import React, { useState, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Send } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState('');

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed) {
      onSend(trimmed);
      setValue('');
    }
  }, [value, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <div className="flex items-end gap-2 px-4 py-3 border-t border-border">
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask about any Azure resource..."
        disabled={disabled}
        className="flex-1 min-h-[40px] max-h-[120px] resize-none"
        rows={1}
      />
      <Button
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        className="h-10 px-4"
      >
        <Send className="h-4 w-4 mr-2" />
        Send Message
      </Button>
    </div>
  );
}
