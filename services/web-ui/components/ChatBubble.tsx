'use client';

import React from 'react';
import { Card, Text, makeStyles, tokens } from '@fluentui/react-components';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const useStyles = makeStyles({
  root: {
    maxWidth: '95%',
    alignSelf: 'flex-start',
    padding: tokens.spacingHorizontalS,
    backgroundColor: tokens.colorNeutralBackground3,
    marginBottom: tokens.spacingVerticalS,
    boxShadow: tokens.shadow2,
    borderRadius: tokens.borderRadiusLarge,
    overflow: 'hidden',
    boxSizing: 'border-box',
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
  tableWrapper: {
    overflowX: 'auto',
    marginTop: tokens.spacingVerticalS,
    marginBottom: tokens.spacingVerticalS,
  },
});

// Inline styles for markdown table elements (Griffel doesn't support descendant selectors)
const tableStyle: React.CSSProperties = {
  borderCollapse: 'collapse',
  width: '100%',
  fontSize: '13px',
  lineHeight: '1.4',
};

const thStyle: React.CSSProperties = {
  padding: '6px 12px',
  textAlign: 'left',
  fontWeight: 600,
  borderBottom: `2px solid`,
  whiteSpace: 'nowrap',
  color: 'inherit',
};

const tdStyle: React.CSSProperties = {
  padding: '5px 12px',
  borderBottom: `1px solid`,
  whiteSpace: 'nowrap',
};

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
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            table: ({ children }) => (
              <div className={styles.tableWrapper}>
                <table style={tableStyle}>{children}</table>
              </div>
            ),
            th: ({ children }) => (
              <th style={thStyle}>{children}</th>
            ),
            td: ({ children }) => (
              <td style={tdStyle}>{children}</td>
            ),
            tr: ({ children }) => (
              <tr>{children}</tr>
            ),
          }}
        >
          {content}
        </ReactMarkdown>
        {isStreaming && <span className={styles.cursor} />}
      </div>
      <Text size={100}>{timestamp}</Text>
    </Card>
  );
}
