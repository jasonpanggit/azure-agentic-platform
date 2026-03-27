'use client';

import React from 'react';
import { Card, Text, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    maxWidth: '85%',
    alignSelf: 'flex-end',
    padding: tokens.spacingHorizontalS,
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    marginBottom: tokens.spacingVerticalS,
  },
});

interface UserBubbleProps {
  content: string;
  timestamp: string;
}

export function UserBubble({ content, timestamp }: UserBubbleProps) {
  const styles = useStyles();

  return (
    <Card className={styles.root} size="small">
      <Text>{content}</Text>
      <Text size={100}>{timestamp}</Text>
    </Card>
  );
}
