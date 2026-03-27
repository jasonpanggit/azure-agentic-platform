'use client';

import React from 'react';
import { Spinner, Text, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
    padding: tokens.spacingVerticalS,
  },
});

interface ThinkingIndicatorProps {
  agentName: string;
}

export function ThinkingIndicator({ agentName }: ThinkingIndicatorProps) {
  const styles = useStyles();

  return (
    <div className={styles.root}>
      <Spinner size="tiny" />
      <Text size={200}>{agentName} Agent is analyzing...</Text>
    </div>
  );
}
