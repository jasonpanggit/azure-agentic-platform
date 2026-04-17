'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentHealthRecord {
  name: string;
  container_app: string;
  status: 'healthy' | 'degraded' | 'offline' | 'unknown';
  last_checked: string;
  last_healthy: string | null;
  consecutive_failures: number;
  latency_ms: number | null;
  endpoint: string;
  error: string | null;
}

interface AgentHealthSummary {
  agents: AgentHealthRecord[];
  total: number;
  healthy_count: number;
  degraded_count: number;
  offline_count: number;
  unknown_count: number;
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.floor(min / 60)}h ago`;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, React.CSSProperties> = {
  healthy: {
    backgroundColor: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
    color: 'var(--accent-green)',
  },
  degraded: {
    backgroundColor: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
    color: 'var(--accent-yellow)',
  },
  offline: {
    backgroundColor: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
    color: 'var(--accent-red)',
  },
  unknown: {
    backgroundColor: 'color-mix(in srgb, var(--text-muted) 15%, transparent)',
    color: 'var(--text-muted)',
  },
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.unknown;
  return (
    <span
      style={style}
      className="inline-block rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Agent card
// ---------------------------------------------------------------------------

function AgentCard({
  record,
  onForceCheck,
  checking,
}: {
  record: AgentHealthRecord;
  onForceCheck: (name: string) => void;
  checking: boolean;
}) {
  return (
    <div
      className="rounded-lg border p-3 flex flex-col gap-1.5"
      style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-surface)' }}
    >
      <div className="flex items-center justify-between gap-1">
        <span
          className="text-[12px] font-semibold truncate"
          style={{ color: 'var(--text-primary)' }}
        >
          {record.name}
        </span>
        <StatusBadge status={record.status} />
      </div>

      <div className="flex items-center justify-between text-[11px]" style={{ color: 'var(--text-muted)' }}>
        <span>{record.latency_ms !== null ? `${record.latency_ms.toFixed(0)}ms` : '—'}</span>
        <span title={record.last_healthy ?? undefined}>
          {record.last_healthy ? relativeTime(record.last_healthy) : '—'}
        </span>
      </div>

      {record.error && (
        <p
          className="text-[10px] truncate"
          style={{ color: 'var(--accent-red)' }}
          title={record.error}
        >
          {record.error}
        </p>
      )}

      <button
        onClick={() => onForceCheck(record.name)}
        disabled={checking}
        className="mt-1 text-[10px] rounded px-2 py-0.5 border transition-opacity disabled:opacity-50"
        style={{
          borderColor: 'var(--border)',
          color: 'var(--text-muted)',
          backgroundColor: 'transparent',
        }}
      >
        {checking ? 'Checking…' : 'Force Check'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton (9 cards)
// ---------------------------------------------------------------------------

function LoadingGrid() {
  return (
    <div className="grid grid-cols-3 gap-3">
      {Array.from({ length: 9 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border p-3 flex flex-col gap-2"
          style={{ borderColor: 'var(--border)' }}
        >
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-5 w-14" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 30_000;

export function AgentHealthPanel() {
  const [summary, setSummary] = useState<AgentHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checkingAgents, setCheckingAgents] = useState<Set<string>>(new Set());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch('/api/proxy/agents/health');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: AgentHealthSummary = await res.json();
      setSummary(data);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    timerRef.current = setInterval(fetchHealth, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchHealth]);

  const handleForceCheck = useCallback(async (name: string) => {
    setCheckingAgents((prev) => new Set(prev).add(name));
    try {
      const res = await fetch(`/api/proxy/agents/${encodeURIComponent(name)}/check`, {
        method: 'POST',
      });
      if (res.ok) {
        const updated: AgentHealthRecord = await res.json();
        setSummary((prev) => {
          if (!prev) return prev;
          const agents = prev.agents.map((a) => (a.name === name ? updated : a));
          return { ...prev, agents };
        });
      }
    } catch (_) {
      // best-effort
    } finally {
      setCheckingAgents((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    }
  }, []);

  // Summary badge counts
  const healthy = summary?.healthy_count ?? 0;
  const degraded = summary?.degraded_count ?? 0;
  const offline = summary?.offline_count ?? 0;
  const unknown = summary?.unknown_count ?? 0;

  return (
    <div
      className="rounded-lg border p-4 flex flex-col gap-4"
      style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-canvas)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3
            className="text-[13px] font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            Agent Health
          </h3>
          {summary && (
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              checked {relativeTime(summary.generated_at)}
            </span>
          )}
        </div>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="flex items-center gap-1 text-[11px] px-2 py-1 rounded border transition-opacity disabled:opacity-50"
          style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>

      {/* Summary badges */}
      <div className="flex items-center gap-2 flex-wrap">
        <span style={STATUS_STYLES.healthy} className="rounded px-2 py-0.5 text-[11px] font-medium">
          Healthy {healthy}
        </span>
        <span style={STATUS_STYLES.degraded} className="rounded px-2 py-0.5 text-[11px] font-medium">
          Degraded {degraded}
        </span>
        <span style={STATUS_STYLES.offline} className="rounded px-2 py-0.5 text-[11px] font-medium">
          Offline {offline}
        </span>
        <span style={STATUS_STYLES.unknown} className="rounded px-2 py-0.5 text-[11px] font-medium">
          Unknown {unknown}
        </span>
      </div>

      {error && (
        <p className="text-[12px]" style={{ color: 'var(--accent-red)' }}>
          {error}
        </p>
      )}

      {/* Agent grid */}
      {loading ? (
        <LoadingGrid />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(summary?.agents ?? []).map((record) => (
            <AgentCard
              key={record.name}
              record={record}
              onForceCheck={handleForceCheck}
              checking={checkingAgents.has(record.name)}
            />
          ))}
          {(summary?.agents.length ?? 0) === 0 && !loading && (
            <p className="text-[12px] col-span-3" style={{ color: 'var(--text-muted)' }}>
              No agent health data yet — first check pending.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
