'use client';

// PLACEHOLDER: replaced by Plan 05-05 Task 5-05-06 with AlertFeed, AuditLogViewer, etc.
// This shell provides the structural component and props interface only.

import React from 'react';
import { Text, makeStyles, tokens } from '@fluentui/react-components';

const useStyles = makeStyles({
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '200px',
    gap: tokens.spacingVerticalM,
  },
});

interface DashboardPanelProps {
  activeTab: string;
  subscriptions: string[];
}

export function DashboardPanel({ activeTab, subscriptions }: DashboardPanelProps) {
  const styles = useStyles();

  const tabContent: Record<string, { heading: string; body: string }> = {
    alerts: {
      heading: 'No alerts',
      body: 'No alerts match your current filters. Adjust the filters above or check back later.',
    },
    topology: {
      heading: 'Topology',
      body: 'Resource topology view will be available in a future update.',
    },
    resources: {
      heading: 'Resources',
      body: 'Resource inventory will load when subscriptions are selected.',
    },
    audit: {
      heading: 'No actions recorded',
      body: 'Agent actions for this time range will appear here once incidents are triaged.',
    },
  };

  const content = tabContent[activeTab] || tabContent.alerts;

  return (
    <div className={styles.emptyState}>
      <Text weight="semibold" size={400}>{content.heading}</Text>
      <Text align="center" size={300}>{content.body}</Text>
    </div>
  );
}
