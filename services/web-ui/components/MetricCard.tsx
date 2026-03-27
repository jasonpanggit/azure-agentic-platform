'use client';

import React from 'react';
import { Card, Text, Badge, makeStyles, tokens } from '@fluentui/react-components';

type HealthStatus = 'healthy' | 'warning' | 'critical';

const useStyles = makeStyles({
  card: {
    backgroundColor: tokens.colorNeutralBackground3,
    borderLeftWidth: '3px',
    borderLeftStyle: 'solid',
  },
  healthy: {
    borderLeftColor: tokens.colorPaletteGreenForeground1,
  },
  warning: {
    borderLeftColor: tokens.colorPaletteYellowForeground1,
  },
  critical: {
    borderLeftColor: tokens.colorPaletteRedForeground1,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: tokens.spacingVerticalS,
  },
  content: {
    padding: tokens.spacingHorizontalM,
  },
});

const BADGE_COLOR_MAP: Record<HealthStatus, 'success' | 'warning' | 'danger'> = {
  healthy: 'success',
  warning: 'warning',
  critical: 'danger',
};

const BADGE_LABEL_MAP: Record<HealthStatus, string> = {
  healthy: 'Healthy',
  warning: 'Degraded',
  critical: 'Critical',
};

interface MetricCardProps {
  title: string;
  health: HealthStatus;
  children: React.ReactNode;
}

export function MetricCard({ title, health, children }: MetricCardProps) {
  const styles = useStyles();

  return (
    <Card
      className={`${styles.card} ${styles[health]}`}
      role="region"
      aria-label={title}
    >
      <div className={styles.content}>
        <div className={styles.header}>
          <Text weight="semibold" size={400}>
            {title}
          </Text>
          <Badge
            color={BADGE_COLOR_MAP[health]}
            appearance="filled"
            aria-label={`Health status: ${BADGE_LABEL_MAP[health]}`}
          >
            {BADGE_LABEL_MAP[health]}
          </Badge>
        </div>
        {children}
      </div>
    </Card>
  );
}

export type { HealthStatus };
