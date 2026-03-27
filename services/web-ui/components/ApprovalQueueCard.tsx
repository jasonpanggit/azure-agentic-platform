'use client';

import React from 'react';
import { Text, makeStyles, tokens } from '@fluentui/react-components';
import { MetricCard, HealthStatus } from './MetricCard';

const useStyles = makeStyles({
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: tokens.spacingVerticalXS,
    paddingBottom: tokens.spacingVerticalXS,
  },
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: '12px' },
});

interface ApprovalQueueData {
  pending: number;
  oldestPendingMinutes: number | null;
}

function getQueueHealth(pending: number): HealthStatus {
  if (pending > 25) return 'critical';
  if (pending > 10) return 'warning';
  return 'healthy';
}

interface ApprovalQueueCardProps {
  data: ApprovalQueueData;
}

export function ApprovalQueueCard({ data }: ApprovalQueueCardProps) {
  const styles = useStyles();
  const health = getQueueHealth(data.pending);

  return (
    <MetricCard title="Approval Queue" health={health}>
      <div className={styles.row}>
        <Text>Pending</Text>
        <span className={styles.mono}>{data.pending}</span>
      </div>
      <div className={styles.row}>
        <Text>Oldest pending</Text>
        <span className={styles.mono}>
          {data.oldestPendingMinutes !== null ? `${data.oldestPendingMinutes}m ago` : 'n/a'}
        </span>
      </div>
    </MetricCard>
  );
}
