'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  AlertTriangle,
  CheckCircle2,
  TrendingUp,
  TrendingDown,
  Minus,
  X,
  RefreshCw,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Advisory {
  advisory_id: string;
  resource_name: string;
  metric_name: string;
  current_value: number;
  baseline_mean: number;
  baseline_stddev: number;
  z_score: number;
  severity: 'warning' | 'critical';
  trend_direction: 'rising' | 'falling' | 'stable';
  estimated_breach_hours: number | null;
  message: string;
  detected_at: string;
  status: string;
  pattern_match: string | null;
}

interface AdvisoryPanelProps {
  subscriptionId?: string;
}

// ---------------------------------------------------------------------------
// Auto-refresh interval
// ---------------------------------------------------------------------------

const REFRESH_MS = 120_000; // 2 minutes

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: 'warning' | 'critical' }) {
  const isCritical = severity === 'critical';
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold"
      style={{
        background: isCritical
          ? 'color-mix(in srgb, var(--accent-red) 15%, transparent)'
          : 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: isCritical ? 'var(--accent-red)' : 'var(--accent-yellow)',
      }}
    >
      {isCritical ? 'CRITICAL' : 'WARNING'}
    </span>
  );
}

function TrendChip({ direction }: { direction: 'rising' | 'falling' | 'stable' }) {
  if (direction === 'rising') {
    return (
      <span
        className="inline-flex items-center gap-0.5 text-[11px]"
        style={{ color: 'var(--accent-red)' }}
      >
        <TrendingUp className="h-3 w-3" />
        Rising
      </span>
    );
  }
  if (direction === 'falling') {
    return (
      <span
        className="inline-flex items-center gap-0.5 text-[11px]"
        style={{ color: 'var(--accent-green)' }}
      >
        <TrendingDown className="h-3 w-3" />
        Falling
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-0.5 text-[11px]"
      style={{ color: 'var(--text-secondary)' }}
    >
      <Minus className="h-3 w-3" />
      Stable
    </span>
  );
}

function AdvisoryCard({
  advisory,
  onDismiss,
}: {
  advisory: Advisory;
  onDismiss: (id: string) => void;
}) {
  const [dismissing, setDismissing] = useState(false);

  async function handleDismiss() {
    setDismissing(true);
    try {
      await fetch(`/api/proxy/advisories/${advisory.advisory_id}/dismiss`, {
        method: 'PATCH',
      });
      onDismiss(advisory.advisory_id);
    } catch {
      setDismissing(false);
    }
  }

  const metricLabel = advisory.metric_name.replace(/_/g, ' ');

  return (
    <div
      className="rounded-lg p-3 flex flex-col gap-2"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
      }}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1 min-w-0">
          <span className="text-[13px] font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
            {advisory.resource_name}
          </span>
          <span className="text-[11px] capitalize" style={{ color: 'var(--text-secondary)' }}>
            {metricLabel}
          </span>
        </div>
        <button
          onClick={() => void handleDismiss()}
          disabled={dismissing}
          className="shrink-0 rounded p-1 transition-colors"
          style={{ color: 'var(--text-secondary)' }}
          aria-label="Dismiss advisory"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Value + z-score */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
          {advisory.metric_name.includes('pct') || advisory.metric_name.includes('percent') || advisory.metric_name.includes('percentage')
            ? `${advisory.current_value.toFixed(1)}%`
            : advisory.current_value.toFixed(1)}
        </span>
        <span
          className="rounded px-1.5 py-0.5 text-[11px] font-semibold"
          style={{
            background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
            color: 'var(--accent-blue)',
          }}
        >
          {Math.abs(advisory.z_score).toFixed(1)}σ above baseline
        </span>
      </div>

      {/* Badges row */}
      <div className="flex items-center gap-2 flex-wrap">
        <SeverityBadge severity={advisory.severity} />
        <TrendChip direction={advisory.trend_direction} />
        {advisory.estimated_breach_hours !== null ? (
          <span
            className="text-[11px] font-medium"
            style={{ color: 'var(--accent-orange, var(--accent-yellow))' }}
          >
            Breach in ~{advisory.estimated_breach_hours.toFixed(1)}h
          </span>
        ) : (
          <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
            No breach predicted
          </span>
        )}
      </div>

      {/* Message */}
      <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
        {advisory.message}
      </p>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-lg p-3 flex flex-col gap-2"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-56" />
          <Skeleton className="h-3 w-full" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AdvisoryPanel({ subscriptionId }: AdvisoryPanelProps) {
  const [advisories, setAdvisories] = useState<Advisory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAdvisories = useCallback(async () => {
    try {
      const params = new URLSearchParams({ status: 'active', limit: '50' });
      if (subscriptionId) params.set('subscription_id', subscriptionId);

      const res = await fetch(`/api/proxy/advisories?${params.toString()}`);
      const data = await res.json() as { advisories?: Advisory[]; error?: string };

      if (!res.ok) {
        setError(data.error ?? 'Failed to load advisories');
        return;
      }

      setAdvisories(data.advisories ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [subscriptionId]);

  useEffect(() => {
    void fetchAdvisories();
    const interval = setInterval(() => void fetchAdvisories(), REFRESH_MS);
    return () => clearInterval(interval);
  }, [fetchAdvisories]);

  async function dismissAll() {
    await Promise.allSettled(
      advisories.map((a) =>
        fetch(`/api/proxy/advisories/${a.advisory_id}/dismiss`, { method: 'PATCH' })
      )
    );
    setAdvisories([]);
  }

  function removeAdvisory(id: string) {
    setAdvisories((prev) => prev.filter((a) => a.advisory_id !== id));
  }

  const count = advisories.length;

  return (
    <div
      className="rounded-xl flex flex-col gap-3 p-4"
      style={{
        background: 'var(--bg-canvas)',
        border: '1px solid var(--border)',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" style={{ color: 'var(--accent-yellow)' }} />
          <span className="text-[13px] font-semibold" style={{ color: 'var(--text-primary)' }}>
            Pre-Incident Advisories
          </span>
          {!loading && (
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
              style={{
                background: count > 0
                  ? 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)'
                  : 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
                color: count > 0 ? 'var(--accent-yellow)' : 'var(--accent-green)',
              }}
            >
              {count}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void fetchAdvisories()}
            className="flex items-center gap-1 text-[11px] px-2 py-1 rounded"
            style={{
              color: 'var(--accent-blue)',
              background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
            }}
          >
            <RefreshCw className="h-3 w-3" />
            Refresh
          </button>
          {count > 0 && (
            <button
              onClick={() => void dismissAll()}
              className="text-[11px] px-2 py-1 rounded"
              style={{
                color: 'var(--text-secondary)',
                background: 'color-mix(in srgb, var(--border) 50%, transparent)',
              }}
            >
              Dismiss All
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      {loading ? (
        <LoadingSkeleton />
      ) : error ? (
        <Alert variant="destructive">
          <AlertDescription className="text-[12px] flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => void fetchAdvisories()}
              className="underline text-[11px] ml-2"
            >
              Retry
            </button>
          </AlertDescription>
        </Alert>
      ) : count === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-8">
          <CheckCircle2 className="h-8 w-8" style={{ color: 'var(--accent-green)' }} />
          <p className="text-[13px] font-medium" style={{ color: 'var(--text-primary)' }}>
            No anomalies detected
          </p>
          <p className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>
            All metrics within normal range
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {advisories.map((advisory) => (
            <AdvisoryCard
              key={advisory.advisory_id}
              advisory={advisory}
              onDismiss={removeAdvisory}
            />
          ))}
        </div>
      )}
    </div>
  );
}
