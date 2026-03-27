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
  Toolbar,
  Dropdown,
  Option,
  Input,
  Text,
  Badge,
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
  filters: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    flexWrap: 'wrap',
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

interface AuditEntry {
  timestamp: string;
  agent: string;
  tool: string;
  outcome: string;
  duration_ms: number;
  properties?: string;
}

interface AuditLogViewerProps {
  incidentId?: string;
}

export function AuditLogViewer({ incidentId }: AuditLogViewerProps) {
  const styles = useStyles();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');

  const fetchAuditLog = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (incidentId) params.set('incident_id', incidentId);
      if (agentFilter) params.set('agent', agentFilter);
      if (actionFilter) params.set('action', actionFilter);

      const res = await fetch(`/api/proxy/audit?${params.toString()}`);
      if (res.ok) {
        setEntries(await res.json());
      }
    } catch {
      // Query failure
    } finally {
      setLoading(false);
    }
  }, [incidentId, agentFilter, actionFilter]);

  useEffect(() => {
    fetchAuditLog();
  }, [fetchAuditLog]);

  const columns: TableColumnDefinition<AuditEntry>[] = [
    createTableColumn<AuditEntry>({
      columnId: 'timestamp',
      renderHeaderCell: () => 'Timestamp',
      renderCell: (item) => <Text size={200}>{new Date(item.timestamp).toLocaleString()}</Text>,
    }),
    createTableColumn<AuditEntry>({
      columnId: 'agent',
      renderHeaderCell: () => 'Agent',
      renderCell: (item) => <Text>{item.agent}</Text>,
    }),
    createTableColumn<AuditEntry>({
      columnId: 'tool',
      renderHeaderCell: () => 'Tool',
      renderCell: (item) => <Text size={200}>{item.tool}</Text>,
    }),
    createTableColumn<AuditEntry>({
      columnId: 'outcome',
      renderHeaderCell: () => 'Outcome',
      renderCell: (item) => (
        <Badge
          color={item.outcome === '200' || item.outcome === 'success' ? 'success' : 'danger'}
          appearance="outline"
        >
          {item.outcome}
        </Badge>
      ),
    }),
    createTableColumn<AuditEntry>({
      columnId: 'duration',
      renderHeaderCell: () => 'Duration',
      renderCell: (item) => <Text size={200}>{item.duration_ms}ms</Text>,
    }),
  ];

  if (entries.length === 0 && !loading) {
    return (
      <div className={styles.emptyState}>
        <Text weight="semibold" size={400}>No actions recorded</Text>
        <Text align="center" size={300}>
          Agent actions for this time range will appear here once incidents are triaged.
        </Text>
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <Toolbar className={styles.filters}>
        <Dropdown
          placeholder="Agent"
          value={agentFilter}
          onOptionSelect={(_, data) => setAgentFilter(data.optionValue as string)}
        >
          <Option value="">All Agents</Option>
          <Option value="compute">Compute</Option>
          <Option value="network">Network</Option>
          <Option value="storage">Storage</Option>
          <Option value="security">Security</Option>
          <Option value="arc">Arc</Option>
          <Option value="sre">SRE</Option>
        </Dropdown>
        <Input
          placeholder="Filter by action..."
          value={actionFilter}
          onChange={(_, data) => setActionFilter(data.value)}
        />
      </Toolbar>

      <DataGrid items={entries} columns={columns} sortable>
        <DataGridHeader>
          <DataGridRow>
            {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
          </DataGridRow>
        </DataGridHeader>
        <DataGridBody<AuditEntry>>
          {({ item, rowId }) => (
            <DataGridRow<AuditEntry> key={rowId}>
              {({ renderCell }) => <DataGridCell>{renderCell(item)}</DataGridCell>}
            </DataGridRow>
          )}
        </DataGridBody>
      </DataGrid>
    </div>
  );
}
