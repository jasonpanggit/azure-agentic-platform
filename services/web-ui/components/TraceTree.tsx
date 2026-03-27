'use client';

import React, { useState } from 'react';
import {
  Tree,
  TreeItem,
  TreeItemLayout,
  makeStyles,
  tokens,
  Text,
  Badge,
} from '@fluentui/react-components';
import {
  WrenchRegular,
  ArrowForwardRegular,
  ShieldCheckmarkRegular,
} from '@fluentui/react-icons';

const useStyles = makeStyles({
  root: {
    borderTop: `1px solid ${tokens.colorNeutralStroke1}`,
    maxHeight: '200px',
    overflow: 'auto',
    padding: tokens.spacingHorizontalS,
  },
  collapsed: {
    cursor: 'pointer',
    padding: tokens.spacingVerticalXS,
  },
  jsonBlock: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: '12px',
    whiteSpace: 'pre-wrap',
    padding: tokens.spacingHorizontalS,
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    maxHeight: '150px',
    overflow: 'auto',
  },
});

export interface TraceEvent {
  type: 'tool_call' | 'handoff' | 'approval_gate' | 'error';
  seq: number;
  name: string;
  durationMs?: number;
  status: 'success' | 'error' | 'pending';
  payload: Record<string, unknown>;
}

interface TraceTreeProps {
  events: TraceEvent[];
}

const typeIcons: Record<string, React.ReactElement> = {
  tool_call: <WrenchRegular />,
  handoff: <ArrowForwardRegular />,
  approval_gate: <ShieldCheckmarkRegular />,
};

export function TraceTree({ events }: TraceTreeProps) {
  const styles = useStyles();
  const [expanded, setExpanded] = useState(false);

  if (events.length === 0) return null;

  return (
    <div className={styles.root}>
      <div
        className={styles.collapsed}
        onClick={() => setExpanded(!expanded)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && setExpanded(!expanded)}
      >
        <Text size={200} weight="semibold">
          Agent Trace ({events.length} events) {expanded ? '▾' : '▸'}
        </Text>
      </div>
      {expanded && (
        <Tree>
          {events.map((event) => (
            <TraceEventNode key={event.seq} event={event} />
          ))}
        </Tree>
      )}
    </div>
  );
}

function TraceEventNode({ event }: { event: TraceEvent }) {
  const styles = useStyles();
  const [showPayload, setShowPayload] = useState(false);

  const statusColor = {
    success: 'success' as const,
    error: 'danger' as const,
    pending: 'warning' as const,
  }[event.status];

  return (
    <TreeItem itemType="leaf">
      <TreeItemLayout
        iconBefore={typeIcons[event.type] || typeIcons.tool_call}
        onClick={() => setShowPayload(!showPayload)}
      >
        <Text size={200}>{event.name}</Text>
        {event.durationMs !== undefined && (
          <Text size={100} style={{ marginLeft: tokens.spacingHorizontalS }}>
            {event.durationMs}ms
          </Text>
        )}
        <Badge
          appearance="filled"
          color={statusColor}
          style={{ marginLeft: tokens.spacingHorizontalS }}
        >
          {event.status}
        </Badge>
      </TreeItemLayout>
      {showPayload && (
        <pre className={styles.jsonBlock}>
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </TreeItem>
  );
}
