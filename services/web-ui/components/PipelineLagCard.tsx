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

interface PipelineLagData {
  alertToIncidentMs: number;
  incidentToTriageMs: number;
  totalE2EMs: number;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getLagHealth(totalMs: number): HealthStatus {
  if (totalMs > 120000) return 'critical';
  if (totalMs > 60000) return 'warning';
  return 'healthy';
}

interface PipelineLagCardProps {
  data: PipelineLagData;
}

export function PipelineLagCard({ data }: PipelineLagCardProps) {
  const styles = useStyles();
  const health = getLagHealth(data.totalE2EMs);

  const rows = [
    { label: 'Alert to Incident', value: data.alertToIncidentMs },
    { label: 'Incident to Triage', value: data.incidentToTriageMs },
    { label: 'Total End-to-End', value: data.totalE2EMs },
  ];

  return (
    <MetricCard title="Pipeline Lag" health={health}>
      {rows.map((row) => (
        <div key={row.label} className={styles.row}>
          <Text>{row.label}</Text>
          <span className={styles.mono}>{formatDuration(row.value)}</span>
        </div>
      ))}
    </MetricCard>
  );
}
