'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Text, Skeleton, SkeletonItem, MessageBar, MessageBarBody,
  makeStyles, tokens,
} from '@fluentui/react-components';
import { PulseRegular } from '@fluentui/react-icons';
import { AgentLatencyCard } from './AgentLatencyCard';
import { PipelineLagCard } from './PipelineLagCard';
import { ApprovalQueueCard } from './ApprovalQueueCard';
import { ActiveErrorsCard } from './ActiveErrorsCard';
import { TimeRangeSelector } from './TimeRangeSelector';

const POLL_INTERVAL_MS = 30_000;

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalL,
    height: '100%',
    containerType: 'inline-size',
  },
  toolbar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: tokens.spacingHorizontalL,
    '@container (max-width: 600px)': {
      gridTemplateColumns: '1fr',
    },
  },
  skeletonCard: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    boxShadow: tokens.shadow2,
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: tokens.spacingVerticalXXL,
    gap: tokens.spacingVerticalM,
  },
  emptyIcon: {
    fontSize: '32px',
    color: tokens.colorNeutralForeground3,
  },
});

interface ObservabilityData {
  agentLatency: { agent: string; p50: number; p95: number }[];
  pipelineLag: { alertToIncidentMs: number; incidentToTriageMs: number; totalE2EMs: number };
  approvalQueue: { pending: number; oldestPendingMinutes: number | null };
  activeErrors: { timestamp: string; agent: string; error: string; detail: string }[];
  lastUpdated: string;
}

interface ObservabilityTabProps {
  subscriptions: string[];
}

export function ObservabilityTab({ subscriptions }: ObservabilityTabProps) {
  const styles = useStyles();
  const [timeRange, setTimeRange] = useState('1h');
  const [data, setData] = useState<ObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`/api/observability?timeRange=${timeRange}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${res.status}`);
      }
      const result: ObservabilityData = await res.json();
      setData(result);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to load observability metrics. Check that Application Insights is connected and try again.'
      );
    } finally {
      setLoading(false);
    }
  }, [timeRange]);

  useEffect(() => {
    setLoading(true);
    fetchData();

    intervalRef.current = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchData]);

  // Suppress unused variable warning — subscriptions reserved for future filtering
  void subscriptions;

  if (loading && !data) {
    return (
      <div className={styles.root}>
        <div className={styles.toolbar}>
          <Text size={200}>Loading...</Text>
          <TimeRangeSelector value={timeRange} onChange={setTimeRange} />
        </div>
        <div className={styles.grid}>
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className={styles.skeletonCard}>
              <Skeleton><SkeletonItem /></Skeleton>
              <Skeleton><SkeletonItem /></Skeleton>
              <Skeleton><SkeletonItem /></Skeleton>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <div className={styles.toolbar}>
        <Text size={200} aria-live="polite">
          Last updated: {data ? new Date(data.lastUpdated).toLocaleString() : 'n/a'}
        </Text>
        <TimeRangeSelector value={timeRange} onChange={setTimeRange} />
      </div>

      {error && (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      )}

      {data && data.agentLatency.length === 0 && data.activeErrors.length === 0 ? (
        <div className={styles.emptyState}>
          <PulseRegular className={styles.emptyIcon} />
          <Text weight="semibold" size={400}>No observability data</Text>
          <Text align="center" size={300}>
            Metrics will appear here once agents process their first incidents.
            Ensure Application Insights is configured and agents are running.
          </Text>
        </div>
      ) : data ? (
        <div className={styles.grid}>
          <AgentLatencyCard data={data.agentLatency} />
          <PipelineLagCard data={data.pipelineLag} />
          <ActiveErrorsCard data={data.activeErrors} />
          <ApprovalQueueCard data={data.approvalQueue} />
        </div>
      ) : null}
    </div>
  );
}
