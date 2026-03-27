'use client';

// PLACEHOLDER: replaced by Plan 05-02 Task 5-02-05 with full chat implementation.
// This shell provides the structural component and props interface only.

import React from 'react';
import { Text, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    padding: tokens.spacingHorizontalL,
  },
  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: tokens.spacingVerticalM,
  },
});

interface ChatPanelProps {
  subscriptions: string[];
}

export function ChatPanel({ subscriptions }: ChatPanelProps) {
  const styles = useStyles();

  return (
    <div className={styles.root}>
      <div className={styles.emptyState}>
        <Text weight="semibold" size={400}>Start a conversation</Text>
        <Text align="center" size={300}>
          Ask about any Azure resource, investigate an incident, or check the status of your infrastructure. Type a message below to begin.
        </Text>
      </div>
    </div>
  );
}
