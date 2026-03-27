'use client';

import React from 'react';
import { Card, Text, makeStyles, tokens } from '@fluentui/react-components';
import ReactMarkdown from 'react-markdown';

const useStyles = makeStyles({
  root: {
    maxWidth: '85%',
    alignSelf: 'flex-start',
    padding: tokens.spacingHorizontalS,
    backgroundColor: tokens.colorNeutralBackground3,
    marginBottom: tokens.spacingVerticalS,
    boxShadow: tokens.shadow2,
    borderRadius: tokens.borderRadiusLarge,
  },
  agentName: {
    marginBottom: tokens.spacingVerticalXS,
  },
  cursor: {
    display: 'inline-block',
    width: '2px',
    height: '14px',
    backgroundColor: tokens.colorNeutralForeground1,
    marginLeft: '1px',
    animationName: {
      '50%': { opacity: 0 },
    },
    animationDuration: '1060ms',
    animationIterationCount: 'infinite',
    animationTimingFunction: 'step-end',
  },
});

interface ChatBubbleProps {
  agentName: string;
  content: string;
  isStreaming: boolean;
  timestamp: string;
}

export function ChatBubble({ agentName, content, isStreaming, timestamp }: ChatBubbleProps) {
  const styles = useStyles();

  return (
    <Card className={styles.root} size="small">
      <Text className={styles.agentName} size={200} weight="semibold">
        {agentName} Agent
      </Text>
      <div>
        <ReactMarkdown>{content}</ReactMarkdown>
        {isStreaming && <span className={styles.cursor} />}
      </div>
      <Text size={100}>{timestamp}</Text>
    </Card>
  );
}
