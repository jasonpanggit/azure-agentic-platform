'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Activity } from 'lucide-react';
import { AgentLatencyCard } from './AgentLatencyCard';
import { PipelineLagCard } from './PipelineLagCard';
import { ApprovalQueueCard } from './ApprovalQueueCard';
import { ActiveErrorsCard } from './ActiveErrorsCard';
import { IncidentThroughputCard } from './IncidentThroughputCard';
import { TimeRangeSelector } from './TimeRangeSelector';

const POLL_INTERVAL_MS = 30_000;

interface ObservabilityData {
  agentLatency: { agent: string; p50: number; p95: number }[];
  pipelineLag: {
    alertToIncidentMs: number;
    incidentToTriageMs: number;
    totalE2EMs: number;
  };
  approvalQueue: { pending: number; oldestPendingMinutes: number | null };
  activeErrors: {
    timestamp: string;
    agent: string;
    error: string;
    detail: string;
  }[];
  incidentThroughput: { hour: string; count: number }[];
  lastUpdated: string;
}

interface ObservabilityTabProps {
  subscriptions: string[];
}

export function ObservabilityTab({ subscriptions }: ObservabilityTabProps) {
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
      <div className="flex flex-col gap-6 h-full">
        <div className="flex justify-between items-center">
          <span className="text-sm text-muted-foreground">Loading...</span>
          <TimeRangeSelector value={timeRange} onChange={setTimeRange} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="flex flex-col gap-2 p-4 bg-card rounded-md shadow-sm"
            >
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 h-full">
      <div className="flex justify-between items-center">
        <span className="text-sm text-muted-foreground" aria-live="polite">
          Last updated:{' '}
          {data ? new Date(data.lastUpdated).toLocaleString() : 'n/a'}
        </span>
        <TimeRangeSelector value={timeRange} onChange={setTimeRange} />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {data &&
      data.agentLatency.length === 0 &&
      data.activeErrors.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 gap-4">
          <Activity className="h-8 w-8 text-muted-foreground" />
          <span className="font-semibold text-base">No observability data</span>
          <span className="text-sm text-muted-foreground text-center">
            Metrics will appear here once agents process their first incidents.
            Ensure Application Insights is configured.
          </span>
        </div>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 gap-4">
            <AgentLatencyCard data={data.agentLatency} />
            <PipelineLagCard data={data.pipelineLag} />
            <IncidentThroughputCard data={data.incidentThroughput ?? []} />
            <ApprovalQueueCard data={data.approvalQueue} />
          </div>
          <div className="mt-4">
            <ActiveErrorsCard data={data.activeErrors} />
          </div>
        </>
      ) : null}
    </div>
  );
}
