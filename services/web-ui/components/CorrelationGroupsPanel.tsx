'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { ChevronDown, ChevronRight, Zap, RefreshCw, AlertTriangle } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CorrelationGroup {
  group_id: string;
  pattern: string;          // subscription_storm | blast_radius | cluster
  title: string;
  incident_ids: string[];
  subscription_ids: string[];
  resource_type: string;
  domain: string;
  time_window_start: string;
  time_window_end: string;
  score: number;
  affected_count: number;
  recommended_action: string;
  detected_at: string;
}

interface CorrelationSummary {
  active_storms: number;
  blast_radius_events: number;
  total_correlated_incidents: number;
  top_affected_resource_type: string | null;
  total_groups: number;
}

interface CorrelationGroupsPanelProps {
  subscriptions?: string[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 60_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function PatternBadge({ pattern }: { pattern: string }) {
  const styles: Record<string, React.CSSProperties> = {
    subscription_storm: {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
    },
    blast_radius: {
      background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
      color: 'var(--accent-orange)',
    },
    cluster: {
      background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
      color: 'var(--accent-blue)',
    },
  };
  const style = styles[pattern] ?? styles['cluster'];
  const label = pattern.replace('_', ' ').toUpperCase();
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold tracking-wide"
      style={style}
    >
      {label}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 70 ? 'var(--accent-red)' : pct >= 40 ? 'var(--accent-orange)' : 'var(--accent-blue)';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full" style={{ background: 'var(--border)' }}>
        <div
          className="h-1.5 rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-xs tabular-nums" style={{ color: 'var(--text-secondary)', minWidth: '2.5rem' }}>
        {pct}%
      </span>
    </div>
  );
}

function GroupCard({ group }: { group: CorrelationGroup }) {
  return (
    <div
      className="rounded-lg p-4 flex flex-col gap-3"
      style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0">
          <span className="text-sm font-medium truncate" style={{ color: 'var(--text-primary)' }}>
            {group.title}
          </span>
          <div className="flex items-center gap-2 flex-wrap">
            <PatternBadge pattern={group.pattern} />
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {group.affected_count} {group.pattern === 'blast_radius' ? 'resource groups' : 'subscriptions'}
            </span>
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {group.incident_ids.length} incidents
            </span>
          </div>
        </div>
      </div>

      <ScoreBar score={group.score} />

      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        {group.recommended_action}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CorrelationGroupsPanel({ subscriptions = [] }: CorrelationGroupsPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [groups, setGroups] = useState<CorrelationGroup[]>([]);
  const [summary, setSummary] = useState<CorrelationSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchGroups = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [groupsRes, summaryRes] = await Promise.all([
        fetch('/api/proxy/correlations/groups'),
        fetch('/api/proxy/correlations/summary'),
      ]);
      if (!groupsRes.ok) throw new Error(`Groups fetch failed: ${groupsRes.status}`);
      if (!summaryRes.ok) throw new Error(`Summary fetch failed: ${summaryRes.status}`);

      const groupsData = await groupsRes.json();
      const summaryData = await summaryRes.json();
      setGroups(groupsData.groups ?? []);
      setSummary(summaryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load correlation groups');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGroups();
    const interval = setInterval(fetchGroups, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchGroups]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      await fetch('/api/proxy/correlations/analyze', { method: 'POST' });
      // Refresh after a short delay to pick up new results
      setTimeout(fetchGroups, 2000);
    } catch {
      // best-effort
    } finally {
      setAnalyzing(false);
    }
  };

  const activeCount = summary?.total_groups ?? groups.length;
  const hasAlerts = (summary?.active_storms ?? 0) > 0 || (summary?.blast_radius_events ?? 0) > 0;

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
    >
      {/* Header — always visible, click to expand */}
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 transition-colors hover:opacity-80 cursor-pointer"
        style={{ background: 'transparent' }}
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2">
          {expanded ? (
            <ChevronDown className="w-4 h-4 shrink-0" style={{ color: 'var(--text-secondary)' }} />
          ) : (
            <ChevronRight className="w-4 h-4 shrink-0" style={{ color: 'var(--text-secondary)' }} />
          )}
          <Zap className="w-4 h-4 shrink-0" style={{ color: hasAlerts ? 'var(--accent-red)' : 'var(--accent-blue)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Active Correlation Groups
          </span>
          {activeCount > 0 && (
            <span
              className="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold"
              style={{
                background: hasAlerts
                  ? 'color-mix(in srgb, var(--accent-red) 20%, transparent)'
                  : 'color-mix(in srgb, var(--accent-blue) 20%, transparent)',
                color: hasAlerts ? 'var(--accent-red)' : 'var(--accent-blue)',
              }}
            >
              {activeCount}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {summary && (
            <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
              {summary.active_storms > 0 && (
                <span style={{ color: 'var(--accent-red)' }}>
                  {summary.active_storms} storm{summary.active_storms !== 1 ? 's' : ''}
                </span>
              )}
              {summary.blast_radius_events > 0 && (
                <span style={{ color: 'var(--accent-orange)' }}>
                  {summary.blast_radius_events} blast radius
                </span>
              )}
              <span>{summary.total_correlated_incidents} correlated incidents</span>
            </div>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--border)' }}>
          <div className="flex items-center justify-between px-4 py-2">
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {groups.length === 0 ? 'No active correlation groups' : `${groups.length} group${groups.length !== 1 ? 's' : ''} detected`}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={(e) => { e.stopPropagation(); fetchGroups(); }}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs transition-opacity hover:opacity-70"
                style={{ color: 'var(--text-secondary)', background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
              >
                <RefreshCw className="w-3 h-3" />
                Refresh
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleAnalyze(); }}
                disabled={analyzing}
                className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                style={{ background: 'var(--accent-blue)', color: '#fff' }}
              >
                {analyzing ? 'Analyzing…' : 'Analyze'}
              </button>
            </div>
          </div>

          {error && (
            <div
              className="mx-4 mb-3 px-3 py-2 rounded text-xs"
              style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', color: 'var(--accent-red)' }}
            >
              {error}
            </div>
          )}

          <div className="px-4 pb-4 flex flex-col gap-3">
            {loading && groups.length === 0 ? (
              [...Array(2)].map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)
            ) : groups.length === 0 ? (
              <div className="py-6 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
                No correlation groups detected. Click &quot;Analyze&quot; to run detection.
              </div>
            ) : (
              groups.map(g => <GroupCard key={g.group_id} group={g} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}
