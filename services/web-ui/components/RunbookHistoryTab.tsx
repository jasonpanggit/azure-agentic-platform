'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { RefreshCw, BookOpen, CheckCircle2, XCircle, Clock, AlertTriangle } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RunbookExecution {
  execution_id: string;
  incident_id: string;
  action_name: string;
  action_class: string;
  resource_id: string;
  resource_name: string;
  resource_group: string;
  subscription_id: string;
  status: string;
  executed_at: string;
  duration_ms: number;
  approved_by: string;
  rollback_available: boolean;
  pre_check_passed: boolean;
  success: boolean;
  notes: string;
}

interface RunbookStats {
  total_executions: number;
  success_rate: number;
  avg_duration_ms: number;
  by_action: Record<string, { count: number; success_rate: number }>;
  by_status: Record<string, number>;
  by_action_class: Record<string, number>;
  top_resources: Array<{ resource_name: string; execution_count: number }>;
  recent_failures: RunbookExecution[];
}

interface RunbookHistoryTabProps {
  subscriptions?: string[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      className="flex flex-col gap-1 px-4 py-3 rounded-lg"
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
    >
      <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span className="text-xl font-semibold" style={{ color: 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, React.CSSProperties> = {
    RESOLVED: { background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)', color: 'var(--accent-green)' },
    IMPROVED: { background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)', color: 'var(--accent-blue)' },
    DEGRADED: { background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)' },
    TIMEOUT:  { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)' },
    BLOCKED:  { background: 'color-mix(in srgb, var(--text-secondary) 15%, transparent)', color: 'var(--text-secondary)' },
  };
  const style = styles[status] ?? styles['BLOCKED'];
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
      style={style}
    >
      {status}
    </span>
  );
}

function ActionClassBadge({ actionClass }: { actionClass: string }) {
  const styles: Record<string, React.CSSProperties> = {
    SAFE:        { background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)', color: 'var(--accent-green)' },
    CAUTIOUS:    { background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)', color: 'var(--accent-yellow)' },
    DESTRUCTIVE: { background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)' },
  };
  const style = styles[actionClass] ?? styles['SAFE'];
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={style}
    >
      {actionClass}
    </span>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function formatTimestamp(iso: string): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RunbookHistoryTab({ subscriptions = [] }: RunbookHistoryTabProps) {
  const [executions, setExecutions] = useState<RunbookExecution[]>([]);
  const [stats, setStats] = useState<RunbookStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterActionClass, setFilterActionClass] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterSub, setFilterSub] = useState<string>('all');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterActionClass !== 'all') params.set('action_class', filterActionClass);
      if (filterStatus !== 'all') params.set('status', filterStatus);
      if (filterSub !== 'all') params.set('subscription_id', filterSub);
      params.set('limit', '100');

      const [historyRes, statsRes] = await Promise.all([
        fetch(`/api/proxy/runbooks/history?${params.toString()}`),
        fetch('/api/proxy/runbooks/stats?days=7'),
      ]);

      if (!historyRes.ok) throw new Error(`History fetch failed: ${historyRes.status}`);
      if (!statsRes.ok) throw new Error(`Stats fetch failed: ${statsRes.status}`);

      const historyData = await historyRes.json();
      const statsData = await statsRes.json();

      setExecutions(historyData.executions ?? []);
      setStats(statsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load runbook history');
    } finally {
      setLoading(false);
    }
  }, [filterActionClass, filterStatus, filterSub]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchData]);

  const failureCount = stats ? (stats.by_status['DEGRADED'] ?? 0) + (stats.by_status['TIMEOUT'] ?? 0) : 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Runbook Execution History
          </h2>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-opacity hover:opacity-80"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Stats bar */}
      {loading && !stats ? (
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Total (7d)" value={stats.total_executions} />
          <StatCard label="Success Rate" value={`${(stats.success_rate * 100).toFixed(1)}%`} />
          <StatCard label="Avg Duration" value={formatDuration(Math.round(stats.avg_duration_ms))} />
          <StatCard label="Failures (7d)" value={failureCount} />
        </div>
      ) : null}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <Select value={filterActionClass} onValueChange={setFilterActionClass}>
          <SelectTrigger className="w-44 h-8 text-xs">
            <SelectValue placeholder="Action Class" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Classes</SelectItem>
            <SelectItem value="SAFE">SAFE</SelectItem>
            <SelectItem value="CAUTIOUS">CAUTIOUS</SelectItem>
            <SelectItem value="DESTRUCTIVE">DESTRUCTIVE</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filterStatus} onValueChange={setFilterStatus}>
          <SelectTrigger className="w-44 h-8 text-xs">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="RESOLVED">RESOLVED</SelectItem>
            <SelectItem value="IMPROVED">IMPROVED</SelectItem>
            <SelectItem value="DEGRADED">DEGRADED</SelectItem>
            <SelectItem value="TIMEOUT">TIMEOUT</SelectItem>
            <SelectItem value="BLOCKED">BLOCKED</SelectItem>
          </SelectContent>
        </Select>

        {subscriptions.length > 1 && (
          <Select value={filterSub} onValueChange={setFilterSub}>
            <SelectTrigger className="w-64 h-8 text-xs">
              <SelectValue placeholder="Subscription" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Subscriptions</SelectItem>
              {subscriptions.map(s => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm"
          style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', color: 'var(--accent-red)', border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)' }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Timestamp</TableHead>
              <TableHead className="text-xs">Action</TableHead>
              <TableHead className="text-xs">Resource</TableHead>
              <TableHead className="text-xs">Class</TableHead>
              <TableHead className="text-xs">Status</TableHead>
              <TableHead className="text-xs">Duration</TableHead>
              <TableHead className="text-xs">Approved By</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && executions.length === 0 ? (
              [...Array(5)].map((_, i) => (
                <TableRow key={i}>
                  {[...Array(7)].map((_, j) => (
                    <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                  ))}
                </TableRow>
              ))
            ) : executions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm" style={{ color: 'var(--text-secondary)' }}>
                  No runbook executions found
                </TableCell>
              </TableRow>
            ) : (
              executions.map(exec => (
                <TableRow key={exec.execution_id}>
                  <TableCell className="text-xs whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                    {formatTimestamp(exec.executed_at)}
                  </TableCell>
                  <TableCell className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                    {exec.action_name || '—'}
                  </TableCell>
                  <TableCell className="text-xs max-w-[180px] truncate" title={exec.resource_id} style={{ color: 'var(--text-primary)' }}>
                    {exec.resource_name || '—'}
                  </TableCell>
                  <TableCell>
                    <ActionClassBadge actionClass={exec.action_class} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={exec.status} />
                  </TableCell>
                  <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {formatDuration(exec.duration_ms)}
                  </TableCell>
                  <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {exec.approved_by || '—'}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
