'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  DataGrid,
  DataGridHeader,
  DataGridRow,
  DataGridHeaderCell,
  DataGridBody,
  DataGridCell,
  TableColumnDefinition,
  createTableColumn,
  Badge,
  Text,
  Skeleton,
  SkeletonItem,
  makeStyles,
  tokens,
} from '@fluentui/react-components';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    height: '100%',
  },
  gridWrapper: {
    borderRadius: tokens.borderRadiusMedium,
    overflow: 'hidden',
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

interface Incident {
  incident_id: string;
  severity: string;
  domain: string;
  status: string;
  created_at: string;
  title?: string;
  resource_id?: string;
}

interface AlertFeedProps {
  subscriptions: string[];
  filters: {
    severity?: string;
    domain?: string;
    status?: string;
  };
}

const severityColors: Record<string, 'danger' | 'warning' | 'informative'> = {
  Sev0: 'danger',
  Sev1: 'danger',
  Sev2: 'warning',
  Sev3: 'warning',
};

const POLL_INTERVAL_MS = 5000;

export function AlertFeed({ subscriptions, filters }: AlertFeedProps) {
  const styles = useStyles();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchIncidents = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (subscriptions.length > 0) {
        params.set('subscription', subscriptions.join(','));
      }
      if (filters.severity) params.set('severity', filters.severity);
      if (filters.domain) params.set('domain', filters.domain);
      if (filters.status) params.set('status', filters.status);

      const res = await fetch(`/api/proxy/incidents?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch {
      // Polling failure — retry on next interval
    } finally {
      setLoading(false);
    }
  }, [subscriptions, filters]);

  useEffect(() => {
    fetchIncidents();
    const interval = setInterval(fetchIncidents, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchIncidents]);

  const columns: TableColumnDefinition<Incident>[] = [
    createTableColumn<Incident>({
      columnId: 'severity',
      renderHeaderCell: () => 'Severity',
      renderCell: (item) => (
        <Badge color={severityColors[item.severity] || 'informative'} appearance="filled">
          {item.severity}
        </Badge>
      ),
    }),
    createTableColumn<Incident>({
      columnId: 'domain',
      renderHeaderCell: () => 'Domain',
      renderCell: (item) => <Text>{item.domain}</Text>,
    }),
    createTableColumn<Incident>({
      columnId: 'resource',
      renderHeaderCell: () => 'Resource',
      renderCell: (item) => (
        <Text size={200} truncate>
          {item.title || item.resource_id || item.incident_id}
        </Text>
      ),
    }),
    createTableColumn<Incident>({
      columnId: 'status',
      renderHeaderCell: () => 'Status',
      renderCell: (item) => <Badge appearance="outline">{item.status}</Badge>,
    }),
    createTableColumn<Incident>({
      columnId: 'time',
      renderHeaderCell: () => 'Time',
      renderCell: (item) => (
        <Text size={200}>{new Date(item.created_at).toLocaleTimeString()}</Text>
      ),
    }),
  ];

  if (loading) {
    return (
      <div>
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i}>
            <SkeletonItem style={{ height: '40px', marginBottom: '4px' }} />
          </Skeleton>
        ))}
      </div>
    );
  }

  if (incidents.length === 0) {
    return (
      <div className={styles.emptyState}>
        <Text weight="semibold" size={400}>No alerts</Text>
        <Text align="center" size={300}>
          No alerts match your current filters. Adjust the filters above or check back later.
        </Text>
      </div>
    );
  }

  return (
    <div className={styles.gridWrapper}>
      <DataGrid
        items={incidents}
        columns={columns}
        getRowId={(item) => item.incident_id}
        sortable
      >
        <DataGridHeader>
          <DataGridRow>
            {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
          </DataGridRow>
        </DataGridHeader>
        <DataGridBody<Incident>>
          {({ item, rowId }) => (
            <DataGridRow<Incident> key={rowId}>
              {({ renderCell }) => <DataGridCell>{renderCell(item)}</DataGridCell>}
            </DataGridRow>
          )}
        </DataGridBody>
      </DataGrid>
    </div>
  );
}
