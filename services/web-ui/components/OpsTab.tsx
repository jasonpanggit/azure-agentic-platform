'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Clock,
  TrendingDown,
  Zap,
  Activity,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 30_000;
const MAX_INCIDENTS_FETCH = 50;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ErrorBudgetEntry {
  slo_id: string;
  error_budget_pct: number;
}

interface PlatformHealth {
  detection_pipeline_lag_seconds: number | null;
  auto_remediation_success_rate: number | null;
  noise_reduction_pct: number | null;
  slo_compliance_pct: number | null;
  automation_savings_count: number;
  mttr_p50_minutes: number | null;
  mttr_p95_minutes: number | null;
  error_budget_portfolio: ErrorBudgetEntry[];
}

interface IncidentSummary {
  incident_id: string;
  severity: string;
  domain: string;
  resource_name: string;
  created_at: string;
  investigation_status: string;
  status?: string;
}

interface ImminentBreach {
  resource_id: string;
  metric: string;
  minutes_to_breach: number;
  confidence: number;
}

interface PatternEntry {
  pattern_type?: string;
  description?: string;
  occurrence_count?: number;
  affected_domains?: string[];
  recommended_action?: string;
  pattern_id?: string;
  domain?: string;
  resource_type?: string | null;
  detection_rule?: string | null;
  incident_count?: number;
  frequency_per_week?: number;
  top_title_words?: string[];
  common_feedback?: string[];
}

interface PatternAnalysis {
  top_patterns: PatternEntry[];
  finops_summary: {
    estimated_monthly_savings_usd: number;
    top_waste_resources: string[];
  };
}

interface OpsData {
  platformHealth: PlatformHealth | null;
  incidents: IncidentSummary[];
  imminentBreaches: ImminentBreach[];
  patterns: PatternAnalysis | null;
  patternsNotFound: boolean;
}

interface SectionError {
  platformHealth: string | null;
  incidents: string | null;
  imminentBreaches: string | null;
  patterns: string | null;
}

interface OpsTabProps {
  subscriptions: string[];
  onNavigateToAlerts?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers — severity sorting & display
// ---------------------------------------------------------------------------

const SEVERITY_ORDER: Record<string, number> = {
  SEV0: 0,
  P1: 0,
  SEV1: 1,
  P2: 1,
  SEV2: 2,
  P3: 2,
  SEV3: 3,
  P4: 3,
};

const INACTIVE_INCIDENT_STATUSES = new Set(['closed', 'suppressed_cascade']);

function severityOrder(sev: string): number {
  return SEVERITY_ORDER[sev.toUpperCase()] ?? 99;
}

function isHighUrgencySeverity(severity: string): boolean {
  const normalized = severity.toUpperCase();
  return normalized === 'SEV0' || normalized === 'SEV1' || normalized === 'P1' || normalized === 'P2';
}

function isActiveIncidentStatus(status: string | undefined): boolean {
  if (!status) return true;
  return !INACTIVE_INCIDENT_STATUSES.has(status.toLowerCase());
}

function severityBadgeStyle(severity: string): React.CSSProperties {
  const s = severity.toUpperCase();
  if (s === 'SEV0' || s === 'P1') {
    return {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      fontWeight: 700,
    };
  }
  if (s === 'SEV1' || s === 'P2') {
    return {
      background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
      color: 'var(--accent-orange)',
      fontWeight: 600,
    };
  }
  if (s === 'SEV2' || s === 'P3') {
    return {
      background: 'color-mix(in srgb, var(--accent-yellow, var(--accent-orange)) 15%, transparent)',
      color: 'var(--accent-yellow, var(--accent-orange))',
      fontWeight: 500,
    };
  }
  return {
    background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
    color: 'var(--accent-blue)',
  };
}

function domainBadgeStyle(): React.CSSProperties {
  return {
    background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
    color: 'var(--accent-blue)',
  };
}

function formatAge(createdAt: string): string {
  const diffMs = Date.now() - new Date(createdAt).getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d ${hrs % 24}h`;
}

function resourceShortName(name: string): string {
  // If it's a full ARM resource ID, take the last segment
  if (name.startsWith('/subscriptions/')) {
    return name.split('/').pop() ?? name;
  }
  return name;
}

// ---------------------------------------------------------------------------
// Helpers — KPI threshold colours
// ---------------------------------------------------------------------------

type ThresholdLevel = 'green' | 'yellow' | 'red' | 'blue';

function mttrLevel(minutes: number | null): ThresholdLevel {
  if (minutes === null) return 'blue';
  if (minutes < 15) return 'green';
  if (minutes < 30) return 'yellow';
  return 'red';
}

function noiseLevel(pct: number | null): ThresholdLevel {
  if (pct === null) return 'blue';
  if (pct > 80) return 'green';
  if (pct > 60) return 'yellow';
  return 'red';
}

function sloLevel(pct: number | null): ThresholdLevel {
  if (pct === null) return 'blue';
  if (pct >= 99.5) return 'green';
  if (pct >= 99) return 'yellow';
  return 'red';
}

function autoRemediationLevel(rate: number | null): ThresholdLevel {
  if (rate === null) return 'blue';
  if (rate >= 80) return 'green';
  if (rate >= 60) return 'yellow';
  return 'red';
}

function pipelineLagLevel(seconds: number | null): ThresholdLevel {
  if (seconds === null) return 'blue';
  if (seconds < 5) return 'green';
  if (seconds < 30) return 'yellow';
  return 'red';
}

const LEVEL_COLORS: Record<ThresholdLevel, { bg: string; text: string }> = {
  green: {
    bg: 'color-mix(in srgb, var(--accent-green) 12%, transparent)',
    text: 'var(--accent-green)',
  },
  yellow: {
    bg: 'color-mix(in srgb, var(--accent-orange) 12%, transparent)',
    text: 'var(--accent-orange)',
  },
  red: {
    bg: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
    text: 'var(--accent-red)',
  },
  blue: {
    bg: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
    text: 'var(--accent-blue)',
  },
};

function levelIcon(level: ThresholdLevel): React.ReactElement {
  const color = LEVEL_COLORS[level].text;
  if (level === 'green') return <CheckCircle2 className="h-3.5 w-3.5" style={{ color }} />;
  if (level === 'yellow') return <AlertTriangle className="h-3.5 w-3.5" style={{ color }} />;
  if (level === 'red') return <XCircle className="h-3.5 w-3.5" style={{ color }} />;
  return <Activity className="h-3.5 w-3.5" style={{ color }} />;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface KpiCardProps {
  label: string;
  value: string;
  subLabel?: string;
  level: ThresholdLevel;
  icon: React.ReactElement;
  loading?: boolean;
}

function KpiCard({ label, value, subLabel, level, icon, loading }: KpiCardProps) {
  const { bg, text } = LEVEL_COLORS[level];
  return (
    <div
      className="flex flex-col gap-1.5 rounded-lg p-4"
      style={{ background: bg, border: `1px solid color-mix(in srgb, ${text} 25%, transparent)` }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
          {label}
        </span>
        {icon}
      </div>
      {loading ? (
        <Skeleton className="h-7 w-20" />
      ) : (
        <span className="text-2xl font-bold tabular-nums" style={{ color: text }}>
          {value}
        </span>
      )}
      {subLabel && (
        <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
          {subLabel}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper with independent error state
// ---------------------------------------------------------------------------

interface SectionProps {
  title: string;
  error: string | null;
  children: React.ReactNode;
}

function Section({ title, error, children }: SectionProps) {
  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
    >
      <div
        className="px-4 py-2.5 text-[12px] font-semibold uppercase tracking-wide"
        style={{
          color: 'var(--text-secondary)',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-subtle)',
        }}
      >
        {title}
      </div>
      {error ? (
        <div className="p-4">
          <Alert variant="destructive">
            <AlertDescription className="text-[12px]">{error}</AlertDescription>
          </Alert>
        </div>
      ) : (
        children
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Incidents table
// ---------------------------------------------------------------------------

interface ActiveIncidentsSectionProps {
  incidents: IncidentSummary[];
  error: string | null;
  loading: boolean;
  onNavigateToAlerts: () => void;
}

function ActiveIncidentsSection({
  incidents,
  error,
  loading,
  onNavigateToAlerts,
}: ActiveIncidentsSectionProps) {
  const p1p2 = incidents
    .filter((incident) => isActiveIncidentStatus(incident.status))
    .filter((incident) => isHighUrgencySeverity(incident.severity))
    .sort((a, b) => {
      const sevDiff = severityOrder(a.severity) - severityOrder(b.severity);
      if (sevDiff !== 0) return sevDiff;
      return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    });

  const shown = p1p2.slice(0, 10);
  const overflow = p1p2.length - shown.length;

  return (
    <Section title="Active Incidents (Sev0 / Sev1)" error={error}>
      {loading && incidents.length === 0 ? (
        <div className="p-4 flex flex-col gap-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
        </div>
      ) : shown.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-6" style={{ color: 'var(--accent-green)' }}>
          <CheckCircle2 className="h-4 w-4" />
          <span className="text-[13px]">No active Sev0 or Sev1 incidents</span>
        </div>
      ) : (
        <div>
          <table className="w-full text-[12px]">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)', width: '60px' }}>Sev</th>
                <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Domain</th>
                <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Resource</th>
                <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)', width: '60px' }}>Age</th>
                <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((inc) => (
                <tr
                  key={inc.incident_id}
                  style={{ borderBottom: '1px solid var(--border)' }}
                >
                  <td className="px-4 py-2">
                    <span
                      className="px-1.5 py-0.5 rounded text-[11px] font-bold"
                      style={severityBadgeStyle(inc.severity)}
                    >
                      {inc.severity.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className="px-1.5 py-0.5 rounded text-[11px]"
                      style={domainBadgeStyle()}
                    >
                      {inc.domain}
                    </span>
                  </td>
                  <td
                    className="px-4 py-2 max-w-[160px] truncate"
                    style={{ color: 'var(--text-primary)' }}
                    title={inc.resource_name}
                  >
                    {resourceShortName(inc.resource_name)}
                  </td>
                  <td className="px-4 py-2 tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                    {formatAge(inc.created_at)}
                  </td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>
                    {inc.investigation_status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {overflow > 0 && (
            <button
              onClick={onNavigateToAlerts}
              className="flex items-center gap-1 px-4 py-2 text-[12px] w-full hover:underline"
              style={{ color: 'var(--accent-blue)', borderTop: '1px solid var(--border)' }}
            >
              View {overflow} more in Alerts tab
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Imminent Breaches section
// ---------------------------------------------------------------------------

interface ImminentBreachesSectionProps {
  breaches: ImminentBreach[];
  error: string | null;
  loading: boolean;
}

function ImminentBreachesSection({ breaches, error, loading }: ImminentBreachesSectionProps) {
  return (
    <Section title="Imminent Breaches (60 min)" error={error}>
      {loading && breaches.length === 0 ? (
        <div className="p-4 flex flex-col gap-2">
          {[1, 2].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
        </div>
      ) : breaches.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-6" style={{ color: 'var(--accent-green)' }}>
          <CheckCircle2 className="h-4 w-4" />
          <span className="text-[13px]">No breaches predicted in next 60 minutes</span>
        </div>
      ) : (
        <div className="flex flex-col gap-0 divide-y" style={{ borderColor: 'var(--border)' }}>
          {breaches.map((b) => {
            const resourceName = resourceShortName(b.resource_id);
            const barPct = Math.min(100, Math.max(0, ((60 - b.minutes_to_breach) / 60) * 100));
            const urgencyColor =
              b.minutes_to_breach <= 15
                ? 'var(--accent-red)'
                : b.minutes_to_breach <= 30
                ? 'var(--accent-orange)'
                : 'var(--accent-yellow, var(--accent-orange))';

            return (
              <div
                key={`${b.resource_id}-${b.metric}`}
                className="px-4 py-3 flex flex-col gap-1.5"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className="text-[11px] font-semibold px-1.5 py-0.5 rounded shrink-0"
                      style={{
                        background: `color-mix(in srgb, ${urgencyColor} 15%, transparent)`,
                        color: urgencyColor,
                      }}
                    >
                      {b.minutes_to_breach}m
                    </span>
                    <span
                      className="text-[12px] font-medium truncate"
                      style={{ color: 'var(--text-primary)' }}
                      title={b.resource_id}
                    >
                      {resourceName}
                    </span>
                    <span className="text-[11px] shrink-0" style={{ color: 'var(--text-secondary)' }}>
                      — {b.metric}
                    </span>
                  </div>
                  <span className="text-[11px] shrink-0 ml-2" style={{ color: 'var(--text-secondary)' }}>
                    {typeof b.confidence === 'number' ? `${Math.round(b.confidence * 100)}% conf.` : b.confidence}
                  </span>
                </div>
                {/* Time-to-breach bar: full bar = 0 min remaining (imminent), empty = 60 min */}
                <div
                  className="h-1.5 rounded-full w-full"
                  style={{ background: 'var(--bg-subtle)' }}
                >
                  <div
                    className="h-1.5 rounded-full transition-all"
                    style={{
                      width: `${barPct}%`,
                      background: urgencyColor,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Patterns section
// ---------------------------------------------------------------------------

interface PatternsSectionProps {
  patterns: PatternAnalysis | null;
  notFound: boolean;
  error: string | null;
  loading: boolean;
}

const PATTERN_TYPE_COLORS: Record<string, string> = {
  cascade: 'var(--accent-red)',
  noise: 'var(--accent-orange)',
  regression: 'var(--accent-orange)',
  capacity: 'var(--accent-blue)',
  security: 'var(--accent-red)',
  compliance: 'var(--accent-orange)',
};

function patternTypeColor(type: string): string {
  return PATTERN_TYPE_COLORS[type.toLowerCase()] ?? 'var(--accent-blue)';
}

function getPatternType(pattern: PatternEntry): string {
  return pattern.pattern_type ?? pattern.domain ?? 'pattern';
}

function getPatternDescription(pattern: PatternEntry): string {
  if (pattern.description) return pattern.description;
  if (pattern.detection_rule) return pattern.detection_rule;
  if (pattern.top_title_words && pattern.top_title_words.length > 0) {
    return pattern.top_title_words.join(', ');
  }
  if (pattern.resource_type) return pattern.resource_type;
  return pattern.pattern_id ?? 'Pattern';
}

function getPatternOccurrenceCount(pattern: PatternEntry): number {
  return pattern.occurrence_count ?? pattern.incident_count ?? 0;
}

function getPatternAffectedDomains(pattern: PatternEntry): string[] {
  if (pattern.affected_domains && pattern.affected_domains.length > 0) {
    return pattern.affected_domains;
  }
  return pattern.domain ? [pattern.domain] : [];
}

function getPatternRecommendedAction(pattern: PatternEntry): string {
  return pattern.recommended_action ?? pattern.common_feedback?.[0] ?? '';
}

function PatternsSection({ patterns, notFound, error, loading }: PatternsSectionProps) {
  return (
    <Section title="Top Recurring Patterns" error={error}>
      {loading && !patterns && !notFound ? (
        <div className="p-4 grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-32 w-full" />)}
        </div>
      ) : notFound ? (
        <div className="flex items-center gap-2 px-4 py-6" style={{ color: 'var(--text-secondary)' }}>
          <Activity className="h-4 w-4 opacity-50" />
          <span className="text-[13px]">Pattern analysis runs weekly. No data yet.</span>
        </div>
      ) : !patterns || patterns.top_patterns.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-6" style={{ color: 'var(--text-secondary)' }}>
          <CheckCircle2 className="h-4 w-4" style={{ color: 'var(--accent-green)' }} />
          <span className="text-[13px]">No recurring patterns detected.</span>
        </div>
      ) : (
        <div className="p-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {patterns.top_patterns.map((p, idx) => {
            const patternType = getPatternType(p);
            const description = getPatternDescription(p);
            const occurrenceCount = getPatternOccurrenceCount(p);
            const affectedDomains = getPatternAffectedDomains(p);
            const recommendedAction = getPatternRecommendedAction(p);
            const typeColor = patternTypeColor(patternType);
            return (
              <div
                key={idx}
                className="flex flex-col gap-2 rounded-md p-3"
                style={{
                  background: 'var(--bg-subtle)',
                  border: '1px solid var(--border)',
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <span
                    className="text-[11px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0"
                    style={{
                      background: `color-mix(in srgb, ${typeColor} 15%, transparent)`,
                      color: typeColor,
                    }}
                  >
                    {patternType}
                  </span>
                  <span
                    className="text-[11px] font-semibold tabular-nums shrink-0"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    ×{occurrenceCount}
                  </span>
                </div>
                <p className="text-[12px] leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                  {description}
                </p>
                {affectedDomains.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {affectedDomains.map((d) => (
                      <span
                        key={d}
                        className="text-[10px] px-1.5 py-0.5 rounded"
                        style={domainBadgeStyle()}
                      >
                        {d}
                      </span>
                    ))}
                  </div>
                )}
                {recommendedAction && (
                  <p
                    className="text-[11px] italic border-t pt-2 mt-1"
                    style={{ color: 'var(--text-secondary)', borderColor: 'var(--border)' }}
                  >
                    → {recommendedAction}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Error Budget Portfolio
// ---------------------------------------------------------------------------

interface ErrorBudgetSectionProps {
  portfolio: ErrorBudgetEntry[];
  loading: boolean;
}

function ErrorBudgetSection({ portfolio, loading }: ErrorBudgetSectionProps) {
  return (
    <Section title="Error Budget Portfolio (SLOs)" error={null}>
      {loading && portfolio.length === 0 ? (
        <div className="p-4 flex flex-col gap-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-6 w-full" />)}
        </div>
      ) : portfolio.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-6" style={{ color: 'var(--text-secondary)' }}>
          <ShieldCheck className="h-4 w-4 opacity-50" />
          <span className="text-[13px]">No SLOs configured yet.</span>
        </div>
      ) : (
        <div className="flex flex-col gap-3 p-4">
          {portfolio.map((entry) => {
            const remaining = Math.max(0, Math.min(100, entry.error_budget_pct ?? 0));
            const consumed = 100 - remaining;
            const budgetColor =
              remaining > 50
                ? 'var(--accent-green)'
                : remaining > 20
                ? 'var(--accent-orange)'
                : 'var(--accent-red)';

            return (
              <div key={entry.slo_id} className="flex flex-col gap-1">
                <div className="flex items-center justify-between text-[12px]">
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {entry.slo_id}
                  </span>
                  <span
                    style={{
                      color: budgetColor,
                      fontWeight: 600,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {remaining.toFixed(1)}% remaining
                  </span>
                </div>
                <div
                  className="h-2.5 rounded-full overflow-hidden flex"
                  style={{ background: 'var(--bg-subtle)' }}
                >
                  {/* Remaining (green/yellow/red) */}
                  <div
                    className="h-full rounded-l-full transition-all"
                    style={{
                      width: `${remaining}%`,
                      background: budgetColor,
                    }}
                  />
                  {/* Consumed (red) */}
                  {consumed > 0 && (
                    <div
                      className="h-full rounded-r-full"
                      style={{
                        width: `${consumed}%`,
                        background: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
                      }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Main OpsTab
// ---------------------------------------------------------------------------

export function OpsTab({ subscriptions, onNavigateToAlerts }: OpsTabProps) {
  const [data, setData] = useState<OpsData>({
    platformHealth: null,
    incidents: [],
    imminentBreaches: [],
    patterns: null,
    patternsNotFound: false,
  });
  const [errors, setErrors] = useState<SectionError>({
    platformHealth: null,
    incidents: null,
    imminentBreaches: null,
    patterns: null,
  });
  const [initialLoading, setInitialLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  // Suppress unused variable warning — subscriptions reserved for future per-subscription filtering
  void subscriptions;

  const fetchAll = useCallback(async () => {
    // Fire all fetches in parallel; each section handles its own error
    const [phRes, incRes, brRes, patRes] = await Promise.allSettled([
      fetch('/api/proxy/ops/platform-health', { signal: AbortSignal.timeout(15000) }),
      // Fetch a broader window and filter active Sev0/Sev1 incidents client-side.
      // The backend supports exact statuses like new/acknowledged/closed, not status=open.
      fetch(`/api/proxy/incidents?limit=${MAX_INCIDENTS_FETCH}`, { signal: AbortSignal.timeout(15000) }),
      fetch('/api/proxy/ops/imminent-breaches', { signal: AbortSignal.timeout(15000) }),
      fetch('/api/proxy/ops/patterns', { signal: AbortSignal.timeout(15000) }),
    ]);

    // ---- Platform Health ----
    let platformHealth: PlatformHealth | null = null;
    let phError: string | null = null;
    if (phRes.status === 'fulfilled') {
      const res = phRes.value;
      if (res.ok) {
        platformHealth = await res.json().catch(() => null);
        if (
          platformHealth !== null &&
          platformHealth?.auto_remediation_success_rate !== null &&
          platformHealth.auto_remediation_success_rate <= 1
        ) {
          platformHealth = {
            ...platformHealth,
            auto_remediation_success_rate: platformHealth.auto_remediation_success_rate * 100,
          };
        }
      } else {
        const body = await res.json().catch(() => ({}));
        phError = body?.error ?? `Platform health unavailable (HTTP ${res.status})`;
      }
    } else {
      phError = `Platform health unreachable: ${phRes.reason instanceof Error ? phRes.reason.message : 'Unknown error'}`;
    }

    // ---- Incidents ----
    let incidents: IncidentSummary[] = [];
    let incError: string | null = null;
    if (incRes.status === 'fulfilled') {
      const res = incRes.value;
      if (res.ok) {
        const body = await res.json().catch(() => []);
        // Backend may return an array directly or { incidents: [] }
        incidents = Array.isArray(body) ? body : (body?.incidents ?? []);
      } else {
        const body = await res.json().catch(() => ({}));
        incError = body?.error ?? `Incidents unavailable (HTTP ${res.status})`;
      }
    } else {
      incError = `Incidents unreachable: ${incRes.reason instanceof Error ? incRes.reason.message : 'Unknown error'}`;
    }

    // ---- Imminent Breaches ----
    let imminentBreaches: ImminentBreach[] = [];
    let brError: string | null = null;
    if (brRes.status === 'fulfilled') {
      const res = brRes.value;
      if (res.ok) {
        const body = await res.json().catch(() => []);
        imminentBreaches = Array.isArray(body) ? body : (body?.imminent_breaches ?? []);
      } else {
        const body = await res.json().catch(() => ({}));
        brError = body?.error ?? `Forecast unavailable (HTTP ${res.status})`;
      }
    } else {
      brError = `Forecast unreachable: ${brRes.reason instanceof Error ? brRes.reason.message : 'Unknown error'}`;
    }

    // ---- Patterns ----
    let patterns: PatternAnalysis | null = null;
    let patError: string | null = null;
    let patternsNotFound = false;
    if (patRes.status === 'fulfilled') {
      const res = patRes.value;
      if (res.status === 404) {
        patternsNotFound = true;
      } else if (res.ok) {
        patterns = await res.json().catch(() => null);
      } else {
        const body = await res.json().catch(() => ({}));
        patError = body?.error ?? `Pattern analysis unavailable (HTTP ${res.status})`;
      }
    } else {
      patError = `Pattern analysis unreachable: ${patRes.reason instanceof Error ? patRes.reason.message : 'Unknown error'}`;
    }

    setData({ platformHealth, incidents, imminentBreaches, patterns, patternsNotFound });
    setErrors({ platformHealth: phError, incidents: incError, imminentBreaches: brError, patterns: patError });
    setLastUpdated(new Date());
    setInitialLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    intervalRef.current = setInterval(fetchAll, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchAll]);

  // Derive overall platform status from health data
  const overallStatus: 'healthy' | 'degraded' | 'critical' | 'unknown' = (() => {
    const ph = data.platformHealth;
    if (!ph) return 'unknown';
    // Treat an all-null payload as unknown so the header does not report healthy before data arrives.
    const hasHealthSignals = [
      ph.detection_pipeline_lag_seconds,
      ph.auto_remediation_success_rate,
      ph.noise_reduction_pct,
      ph.slo_compliance_pct,
      ph.mttr_p50_minutes,
      ph.mttr_p95_minutes,
    ].some((value) => value !== null);
    if (!hasHealthSignals && ph.error_budget_portfolio.length === 0 && ph.automation_savings_count === 0) {
      return 'unknown';
    }
    if (
      (ph.slo_compliance_pct !== null && ph.slo_compliance_pct < 99) ||
      (ph.detection_pipeline_lag_seconds !== null && ph.detection_pipeline_lag_seconds >= 30)
    ) return 'critical';
    if (
      (ph.slo_compliance_pct !== null && ph.slo_compliance_pct < 99.5) ||
      (ph.auto_remediation_success_rate !== null && ph.auto_remediation_success_rate < 60) ||
      (ph.detection_pipeline_lag_seconds !== null && ph.detection_pipeline_lag_seconds >= 5)
    ) return 'degraded';
    return 'healthy';
  })();

  const statusConfig = {
    healthy: { label: 'Platform Healthy', color: 'var(--accent-green)', Icon: CheckCircle2 },
    degraded: { label: 'Platform Degraded', color: 'var(--accent-orange)', Icon: AlertTriangle },
    critical: { label: 'Platform Critical', color: 'var(--accent-red)', Icon: XCircle },
    unknown: { label: 'Platform Status Unknown', color: 'var(--text-secondary)', Icon: Activity },
  }[overallStatus];

  const ph = data.platformHealth;
  const mttrP50 = ph?.mttr_p50_minutes ?? null;
  const mttrP95 = ph?.mttr_p95_minutes ?? null;
  const noisePct = ph?.noise_reduction_pct ?? null;
  const sloPct = ph?.slo_compliance_pct ?? null;
  const autoRate = ph?.auto_remediation_success_rate ?? null;
  const lagSec = ph?.detection_pipeline_lag_seconds ?? null;
  const savingsCount = ph?.automation_savings_count ?? 0;
  const errorBudget = ph?.error_budget_portfolio ?? [];

  const formatPct = (v: number | null, multiplier = 1): string =>
    v === null ? '—' : `${(v * multiplier).toFixed(1)}%`;

  return (
    <div className="flex flex-col gap-5">
      {/* ------------------------------------------------------------------ */}
      {/* Header bar                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div
        className="flex items-center justify-between px-4 py-2.5 rounded-lg"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <statusConfig.Icon className="h-4 w-4" style={{ color: statusConfig.color }} />
          <span className="text-[13px] font-semibold" style={{ color: statusConfig.color }}>
            {statusConfig.label}
          </span>
          <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
            · Auto-refresh 30s
          </span>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
              Last updated: {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => { void fetchAll(); }}
            className="flex items-center gap-1.5 text-[12px] px-2 py-1 rounded"
            style={{
              color: 'var(--accent-blue)',
              background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* KPI row                                                             */}
      {/* ------------------------------------------------------------------ */}
      {errors.platformHealth && (
        <Alert variant="destructive">
          <AlertDescription className="text-[12px]">{errors.platformHealth}</AlertDescription>
        </Alert>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <KpiCard
          label="MTTR P50"
          value={mttrP50 === null ? '—' : `${mttrP50.toFixed(0)}m`}
          subLabel={mttrP95 !== null ? `P95: ${mttrP95.toFixed(0)}m` : undefined}
          level={mttrLevel(mttrP50)}
          icon={levelIcon(mttrLevel(mttrP50))}
          loading={initialLoading}
        />
        <KpiCard
          label="Noise Reduction"
          value={noisePct === null ? '—' : `${noisePct.toFixed(0)}%`}
          level={noiseLevel(noisePct)}
          icon={<TrendingDown className="h-3.5 w-3.5" style={{ color: LEVEL_COLORS[noiseLevel(noisePct)].text }} />}
          loading={initialLoading}
        />
        <KpiCard
          label="SLO Compliance"
          value={formatPct(sloPct)}
          level={sloLevel(sloPct)}
          icon={levelIcon(sloLevel(sloPct))}
          loading={initialLoading}
        />
        <KpiCard
          label="Auto-Remediation"
          value={formatPct(autoRate)}
          level={autoRemediationLevel(autoRate)}
          icon={<Zap className="h-3.5 w-3.5" style={{ color: LEVEL_COLORS[autoRemediationLevel(autoRate)].text }} />}
          loading={initialLoading}
        />
        <KpiCard
          label="Pipeline Lag"
          value={lagSec === null ? '—' : `${lagSec.toFixed(1)}s`}
          level={pipelineLagLevel(lagSec)}
          icon={<Clock className="h-3.5 w-3.5" style={{ color: LEVEL_COLORS[pipelineLagLevel(lagSec)].text }} />}
          loading={initialLoading}
        />
        <KpiCard
          label="Savings 30d"
          value={savingsCount.toString()}
          subLabel="automated actions"
          level="blue"
          icon={<ShieldCheck className="h-3.5 w-3.5" style={{ color: LEVEL_COLORS.blue.text }} />}
          loading={initialLoading}
        />
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Middle row: Incidents + Imminent Breaches                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActiveIncidentsSection
          incidents={data.incidents}
          error={errors.incidents}
          loading={initialLoading}
          onNavigateToAlerts={() => {
            if (onNavigateToAlerts) {
              onNavigateToAlerts();
              return;
            }
            window.dispatchEvent(new CustomEvent('aap:navigate-tab', { detail: 'alerts' }));
          }}
        />
        <ImminentBreachesSection
          breaches={data.imminentBreaches}
          error={errors.imminentBreaches}
          loading={initialLoading}
        />
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Patterns                                                            */}
      {/* ------------------------------------------------------------------ */}
      <PatternsSection
        patterns={data.patterns}
        notFound={data.patternsNotFound}
        error={errors.patterns}
        loading={initialLoading}
      />

      {/* ------------------------------------------------------------------ */}
      {/* Error Budget Portfolio                                              */}
      {/* ------------------------------------------------------------------ */}
      <ErrorBudgetSection
        portfolio={errorBudget}
        loading={initialLoading}
      />
    </div>
  );
}
