'use client';

import React, { useState, useCallback } from 'react';
import { Textarea, Button, makeStyles, tokens } from '@fluentui/react-components';
import { SendRegular } from '@fluentui/react-icons';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingHorizontalL,
    borderTop: `1px solid ${tokens.colorNeutralStroke1}`,
  },
  textarea: {
    flex: 1,
  },
});

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const styles = useStyles();
  const [value, setValue] = useState('');

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed) {
      onSend(trimmed);
      setValue('');
    }
  }, [value, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className={styles.root}>
      <Textarea
        className={styles.textarea}
        placeholder="Type a message..."
        value={value}
        onChange={(_, data) => setValue(data.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        resize="vertical"
        rows={1}
      />
      <Button
        appearance="primary"
        icon={<SendRegular />}
        onClick={handleSend}
        disabled={disabled || !value.trim()}
      >
        Send Message
      </Button>
    </div>
  );
}
