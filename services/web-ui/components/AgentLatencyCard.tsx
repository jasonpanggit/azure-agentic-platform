'use client';

import React from 'react';
import {
  DataGrid, DataGridHeader, DataGridRow, DataGridHeaderCell,
  DataGridBody, DataGridCell, TableColumnDefinition,
  createTableColumn, Text, makeStyles, tokens,
} from '@fluentui/react-components';
import { MetricCard, HealthStatus } from './MetricCard';

const useStyles = makeStyles({
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: '12px' },
  healthy: { color: tokens.colorPaletteGreenForeground1 },
  warning: { color: tokens.colorPaletteYellowForeground1 },
  critical: { color: tokens.colorPaletteRedForeground1 },
});

interface AgentLatencyRow {
  agent: string;
  p50: number;
  p95: number;
}

function getP95Health(p95: number): HealthStatus {
  if (p95 > 5000) return 'critical';
  if (p95 > 3000) return 'warning';
  return 'healthy';
}

interface AgentLatencyCardProps {
  data: AgentLatencyRow[];
}

export function AgentLatencyCard({ data }: AgentLatencyCardProps) {
  const styles = useStyles();
  const worstHealth = data.reduce<HealthStatus>(
    (worst, row) => {
      const h = getP95Health(row.p95);
      if (h === 'critical') return 'critical';
      if (h === 'warning' && worst !== 'critical') return 'warning';
      return worst;
    },
    'healthy'
  );

  const columns: TableColumnDefinition<AgentLatencyRow>[] = [
    createTableColumn<AgentLatencyRow>({
      columnId: 'agent',
      renderHeaderCell: () => 'Agent',
      renderCell: (item) => <Text>{item.agent}</Text>,
    }),
    createTableColumn<AgentLatencyRow>({
      columnId: 'p50',
      renderHeaderCell: () => 'P50',
      renderCell: (item) => <span className={styles.mono}>{item.p50}ms</span>,
    }),
    createTableColumn<AgentLatencyRow>({
      columnId: 'p95',
      renderHeaderCell: () => 'P95',
      renderCell: (item) => {
        const h = getP95Health(item.p95);
        return <span className={`${styles.mono} ${styles[h]}`}>{item.p95}ms</span>;
      },
    }),
  ];

  return (
    <MetricCard title="Agent Latency" health={worstHealth}>
      <DataGrid items={data} columns={columns}>
        <DataGridHeader>
          <DataGridRow>
            {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
          </DataGridRow>
        </DataGridHeader>
        <DataGridBody<AgentLatencyRow>>
          {({ item, rowId }) => (
            <DataGridRow<AgentLatencyRow> key={rowId}>
              {({ renderCell }) => <DataGridCell>{renderCell(item)}</DataGridCell>}
            </DataGridRow>
          )}
        </DataGridBody>
      </DataGrid>
    </MetricCard>
  );
}
