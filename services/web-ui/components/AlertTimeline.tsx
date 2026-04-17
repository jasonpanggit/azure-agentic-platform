'use client'

import { useState, useEffect } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { GitBranch, Clock, Layers, AlertTriangle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ScoreBreakdown {
  temporal_score: number
  topology_score: number
  change_type_score: number
  weighted_total: number
}

interface ChangeCorrelation {
  operation_name: string
  resource_id: string
  resource_name: string
  caller: string | null
  timestamp: string | null
  correlation_score: number
  score_breakdown: ScoreBreakdown
  reason_chips: string[]
}

interface NoiseReduction {
  suppression_reason: string | null
  composite_severity_reason: string | null
  correlation_window_minutes: number
}

interface AlertTimelineData {
  incident_id: string
  title: string
  severity: string | null
  composite_severity: string | null
  detected_at: string | null
  suppressed: boolean
  parent_incident_id: string | null
  blast_radius: number | null
  correlation_summary: string
  change_correlations: ChangeCorrelation[]
  noise_reduction: NoiseReduction
  generated_at: string
}

export interface AlertTimelineProps {
  incidentId: string
}

// ---------------------------------------------------------------------------
// Helper utilities
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    ' ' + d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function operationIcon(operationName: string): string {
  const op = operationName.toLowerCase()
  if (op.includes('write')) return '✏️'
  if (op.includes('delete')) return '🗑️'
  if (op.includes('action')) return '⚡'
  return '🔧'
}

function chipStyle(chip: string): React.CSSProperties {
  const lower = chip.toLowerCase()
  if (lower.startsWith('temporal')) {
    return {
      background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
      color: 'var(--accent-blue)',
    }
  }
  if (lower.startsWith('same resource') || lower.startsWith('topology')) {
    return {
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
    }
  }
  if (lower.startsWith('write') || lower.startsWith('delete') || lower.startsWith('high-impact')) {
    return {
      background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
      color: 'var(--accent-orange)',
    }
  }
  return {
    background: 'color-mix(in srgb, var(--accent-purple) 15%, transparent)',
    color: 'var(--accent-purple)',
  }
}

function scoreBarColor(score: number): string {
  if (score >= 0.8) return 'var(--accent-green)'
  if (score >= 0.5) return 'var(--accent-yellow)'
  return 'var(--accent-red)'
}

function severityColor(sev: string | null): string {
  if (!sev) return 'var(--text-muted)'
  const s = sev.toLowerCase()
  if (s.includes('sev0') || s.includes('critical')) return 'var(--accent-red)'
  if (s.includes('sev1') || s.includes('high')) return 'var(--accent-orange)'
  if (s.includes('sev2') || s.includes('medium')) return 'var(--accent-yellow)'
  return 'var(--accent-green)'
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ReasonChip({ label }: { label: string }) {
  return (
    <span
      className="inline-block text-[10px] font-medium px-1.5 py-0.5 rounded"
      style={chipStyle(label)}
    >
      {label}
    </span>
  )
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1.5 rounded-full flex-1 max-w-[80px] overflow-hidden"
        style={{ background: 'var(--bg-subtle)' }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: scoreBarColor(score) }}
        />
      </div>
      <span className="text-[10px] font-mono tabular-nums" style={{ color: 'var(--text-muted)' }}>
        {pct}%
      </span>
    </div>
  )
}

function ChangeEventRow({ change, index }: { change: ChangeCorrelation; index: number }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      className="relative pl-8"
      style={{ borderLeft: '2px solid var(--border)' }}
    >
      {/* Timeline dot */}
      <div
        className="absolute -left-[9px] top-3 w-4 h-4 rounded-full border-2 flex items-center justify-center text-[10px]"
        style={{
          background: 'var(--bg-canvas)',
          borderColor: scoreBarColor(change.correlation_score),
        }}
      >
        {index + 1}
      </div>

      <div
        className="mb-4 rounded-lg p-3 cursor-pointer"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        onClick={() => setExpanded((v) => !v)}
        role="button"
        aria-expanded={expanded}
      >
        {/* Top row */}
        <div className="flex items-start gap-2 flex-wrap">
          <span className="text-base leading-none" aria-hidden>
            {operationIcon(change.operation_name)}
          </span>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>
                {change.resource_name || '—'}
              </span>
              <span
                className="font-mono text-[11px] truncate max-w-[240px]"
                style={{ color: 'var(--text-muted)' }}
                title={change.operation_name}
              >
                {change.operation_name}
              </span>
            </div>

            {/* Timestamp + caller */}
            <div className="flex items-center gap-3 mt-0.5 flex-wrap">
              <span className="flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                <Clock className="w-3 h-3" />
                {formatTimestamp(change.timestamp)}
              </span>
              {change.caller && (
                <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  by {change.caller}
                </span>
              )}
            </div>
          </div>

          {/* Score bar */}
          <div className="flex-shrink-0 w-28">
            <ScoreBar score={change.correlation_score} />
          </div>
        </div>

        {/* Reason chips */}
        {change.reason_chips.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {change.reason_chips.map((chip) => (
              <ReasonChip key={chip} label={chip} />
            ))}
          </div>
        )}

        {/* Expanded: score breakdown */}
        {expanded && (
          <div
            className="mt-3 pt-3 text-[11px] grid grid-cols-2 gap-x-4 gap-y-1"
            style={{ borderTop: '1px solid var(--border)', color: 'var(--text-muted)' }}
          >
            <span>Temporal score</span>
            <span className="font-mono">{change.score_breakdown.temporal_score}</span>
            <span>Topology score</span>
            <span className="font-mono">{change.score_breakdown.topology_score}</span>
            <span>Change-type score</span>
            <span className="font-mono">{change.score_breakdown.change_type_score}</span>
            <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>Weighted total</span>
            <span className="font-mono font-semibold" style={{ color: 'var(--text-primary)' }}>
              {change.score_breakdown.weighted_total}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AlertTimeline({ incidentId }: AlertTimelineProps) {
  const [data, setData] = useState<AlertTimelineData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`/api/proxy/incidents/${encodeURIComponent(incidentId)}/alert-timeline`)
        const json = await res.json()
        if (!res.ok) {
          setError(json?.error ?? `Failed to load timeline: ${res.status}`)
          return
        }
        if (!cancelled) setData(json as AlertTimelineData)
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to reach API gateway')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => { cancelled = true }
  }, [incidentId])

  // --- Loading skeleton ---
  if (loading) {
    return (
      <div className="space-y-4 p-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-64" />
        <div className="flex gap-2 mt-2">
          <Skeleton className="h-6 w-20 rounded-full" />
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-6 w-28 rounded-full" />
        </div>
        {[1, 2, 3].map((i) => (
          <div key={i} className="pl-8" style={{ borderLeft: '2px solid var(--border)' }}>
            <Skeleton className="h-20 rounded-lg mb-4" />
          </div>
        ))}
      </div>
    )
  }

  // --- Error state ---
  if (error) {
    return (
      <div
        className="flex items-center gap-2 px-4 py-6 text-sm rounded-lg"
        style={{ color: 'var(--accent-red)', background: 'color-mix(in srgb, var(--accent-red) 8%, transparent)' }}
      >
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        <span>{error}</span>
      </div>
    )
  }

  // --- Empty state (no data) ---
  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-2">
        <GitBranch className="w-8 h-8" style={{ color: 'var(--text-muted)' }} />
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No correlation data found</p>
      </div>
    )
  }

  const hasCorrelations = data.change_correlations.length > 0

  return (
    <div className="space-y-5 p-4">
      {/* Header */}
      <div>
        <h3 className="flex items-center gap-2 font-semibold text-base" style={{ color: 'var(--text-primary)' }}>
          <GitBranch className="w-4 h-4" style={{ color: 'var(--accent-blue)' }} />
          🔍 Alert Correlation Analysis
        </h3>
        <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
          powered by change correlator
        </p>
      </div>

      {/* Suppressed banner */}
      {data.suppressed && (
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-yellow) 12%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent-yellow) 40%, transparent)',
            color: 'var(--accent-yellow)',
          }}
        >
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>
            This incident was suppressed — a parent incident covers the same blast radius.
            {data.parent_incident_id && (
              <> Parent: <span className="font-mono">{data.parent_incident_id}</span></>
            )}
          </span>
        </div>
      )}

      {/* Summary row */}
      <div className="flex flex-wrap gap-2">
        {data.blast_radius != null && (
          <span
            className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
              color: 'var(--accent-blue)',
            }}
          >
            <Layers className="w-3 h-3" />
            Blast radius {data.blast_radius}
          </span>
        )}

        {data.composite_severity && data.composite_severity !== data.severity && (
          <span
            className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
              color: severityColor(data.composite_severity),
            }}
          >
            Escalated → {data.composite_severity}
          </span>
        )}

        <span
          className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full"
          style={{
            background: 'var(--bg-subtle)',
            color: 'var(--text-muted)',
          }}
        >
          <Clock className="w-3 h-3" />
          {data.noise_reduction.correlation_window_minutes}m window
        </span>
      </div>

      {/* Correlation summary */}
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        {data.correlation_summary}
      </p>

      {/* Timeline */}
      {hasCorrelations ? (
        <div className="space-y-0 mt-2">
          {data.change_correlations.map((change, i) => (
            <ChangeEventRow key={`${change.resource_id}-${i}`} change={change} index={i} />
          ))}
        </div>
      ) : (
        <div
          className="text-sm px-3 py-4 rounded-lg text-center"
          style={{ color: 'var(--text-muted)', background: 'var(--bg-subtle)' }}
        >
          No correlation data yet — correlator runs within 30s of incident creation
        </div>
      )}

      {/* Noise reduction section */}
      {(data.noise_reduction.composite_severity_reason || data.noise_reduction.suppression_reason) && (
        <div
          className="rounded-lg p-3 text-sm space-y-1"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          <p className="font-semibold text-xs uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
            Noise Reduction
          </p>
          {data.noise_reduction.composite_severity_reason && (
            <p style={{ color: 'var(--text-secondary)' }}>
              <span className="font-medium" style={{ color: 'var(--text-primary)' }}>Severity escalation: </span>
              {data.noise_reduction.composite_severity_reason}
            </p>
          )}
          {data.noise_reduction.suppression_reason && (
            <p style={{ color: 'var(--text-secondary)' }}>
              <span className="font-medium" style={{ color: 'var(--text-primary)' }}>Suppressed because: </span>
              {data.noise_reduction.suppression_reason}
            </p>
          )}
        </div>
      )}

      {/* Footer */}
      <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
        Generated {formatTimestamp(data.generated_at)}
      </p>
    </div>
  )
}
