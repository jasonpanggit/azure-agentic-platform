'use client';

import React from 'react';
import {
  Accordion, AccordionItem, AccordionHeader, AccordionPanel,
  Text, makeStyles, tokens,
} from '@fluentui/react-components';
import { MetricCard } from './MetricCard';

const useStyles = makeStyles({
  detail: { fontFamily: tokens.fontFamilyMonospace, fontSize: '12px' },
  empty: { padding: tokens.spacingVerticalM, textAlign: 'center' },
});

interface ActiveError {
  timestamp: string;
  agent: string;
  error: string;
  detail: string;
}

interface ActiveErrorsCardProps {
  data: ActiveError[];
}

export function ActiveErrorsCard({ data }: ActiveErrorsCardProps) {
  const styles = useStyles();
  const health = data.length > 0 ? 'critical' as const : 'healthy' as const;

  return (
    <MetricCard title="Active Errors" health={health}>
      {data.length === 0 ? (
        <div className={styles.empty}>
          <Text>No active errors</Text>
        </div>
      ) : (
        <Accordion collapsible>
          {data.map((err, idx) => (
            <AccordionItem key={idx} value={String(idx)}>
              <AccordionHeader>
                <Text size={200}>
                  {new Date(err.timestamp).toLocaleTimeString()} {err.agent} — {err.error}
                </Text>
              </AccordionHeader>
              <AccordionPanel>
                <pre className={styles.detail}>{err.detail}</pre>
              </AccordionPanel>
            </AccordionItem>
          ))}
        </Accordion>
      )}
    </MetricCard>
  );
}
