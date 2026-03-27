'use client';
/**
 * DashboardPanel — right pane of the split-pane layout.
 *
 * Tabs: Alerts | Audit | Topology | Resources
 *
 * - alerts:    AlertFilters + AlertFeed (UI-006, UI-007)
 * - audit:     AuditLogViewer (AUDIT-004)
 * - topology:  placeholder (Phase 6)
 * - resources: placeholder (Phase 6)
 *
 * Replaces the Plan 05-01 shell (Task 5-01-07).
 */

import React, { useState } from 'react';
import {
  Tab,
  TabList,
  SelectTabData,
  SelectTabEvent,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';

import { AlertFeed } from './AlertFeed';
import { AlertFilters } from './AlertFilters';
import { AuditLogViewer } from './AuditLogViewer';
import { ObservabilityTab } from './ObservabilityTab';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  tabContent: {
    flex: 1,
    overflow: 'auto',
    padding: tokens.spacingVerticalM,
  },
  alertsContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    height: '100%',
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: tokens.spacingVerticalXXL,
    gap: tokens.spacingVerticalM,
  },
});

type DashboardTab = 'alerts' | 'audit' | 'topology' | 'resources' | 'observability';

interface FilterState {
  severity?: string;
  domain?: string;
  status?: string;
}

interface DashboardPanelProps {
  subscriptions: string[];
  selectedIncidentId?: string;
}

export function DashboardPanel({ subscriptions, selectedIncidentId }: DashboardPanelProps) {
  const styles = useStyles();
  const [activeTab, setActiveTab] = useState<DashboardTab>('alerts');
  const [filters, setFilters] = useState<FilterState>({});

  const handleTabSelect = (_event: SelectTabEvent, data: SelectTabData) => {
    setActiveTab(data.value as DashboardTab);
  };

  return (
    <div className={styles.root}>
      <TabList selectedValue={activeTab} onTabSelect={handleTabSelect}>
        <Tab value="alerts">Alerts</Tab>
        <Tab value="audit">Audit</Tab>
        <Tab value="topology">Topology</Tab>
        <Tab value="resources">Resources</Tab>
        <Tab value="observability">Observability</Tab>
      </TabList>

      <div className={styles.tabContent}>
        {activeTab === 'alerts' && (
          <div className={styles.alertsContainer}>
            <AlertFilters filters={filters} onChange={setFilters} />
            <AlertFeed subscriptions={subscriptions} filters={filters} />
          </div>
        )}

        {activeTab === 'audit' && (
          <AuditLogViewer incidentId={selectedIncidentId} />
        )}

        {activeTab === 'topology' && (
          <div className={styles.emptyState}>
            <Text weight="semibold" size={400}>Topology view</Text>
            <Text align="center" size={300}>
              Resource topology visualization coming in Phase 6.
            </Text>
          </div>
        )}

        {activeTab === 'resources' && (
          <div className={styles.emptyState}>
            <Text weight="semibold" size={400}>Resources</Text>
            <Text align="center" size={300}>
              Multi-subscription resource inventory coming in Phase 6.
            </Text>
          </div>
        )}

        {activeTab === 'observability' && (
          <ObservabilityTab subscriptions={subscriptions} />
        )}
      </div>
    </div>
  );
}
