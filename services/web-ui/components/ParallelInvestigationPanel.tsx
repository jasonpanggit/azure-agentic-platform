'use client'

import React, { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Loader2, CheckCircle2, XCircle, Clock } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DomainStatus = 'pending' | 'running' | 'completed' | 'error'

interface DomainState {
  domain: string
  status: DomainStatus
  duration_ms?: number
}

interface Hypothesis {
  rank: number
  description: string
  evidence: string[]
  confidence: number
}

interface ParallelInvestigationPanelProps {
  /** Domains being investigated — set on fan_out SSE event. */
  domains: string[]
  /** Unique investigation run ID from the orchestrator. */
  investigationId: string
  /** Called when a domain_result SSE event is received for a domain. */
  domainResults?: Record<string, { status: string; duration_ms: number }>
  /** Synthesis text received when all domains complete. */
  synthesis?: string
  /** Ranked hypotheses from correlate_multi_domain. */
  hypotheses?: Hypothesis[]
  /** Total wall-clock duration for the full fan-out (ms). */
  totalDurationMs?: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DOMAIN_LABELS: Record<string, string> = {
  compute: 'Compute',
  network: 'Network',
  security: 'Security',
  storage: 'Storage',
  arc: 'Arc',
  patch: 'Patch',
  sre: 'SRE',
  eol: 'EOL',
  database: 'Database',
}

function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain.toLowerCase()] ?? domain
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function confidencePct(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

// ---------------------------------------------------------------------------
// DomainRow — per-agent status indicator
// ---------------------------------------------------------------------------

function DomainRow({ state }: { state: DomainState }) {
  const icon = () => {
    switch (state.status) {
      case 'running':
        return <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--accent-blue)' }} />
      case 'completed':
        return <CheckCircle2 className="w-4 h-4" style={{ color: 'var(--accent-green)' }} />
      case 'error':
        return <XCircle className="w-4 h-4" style={{ color: 'var(--accent-red)' }} />
      default:
        return <Clock className="w-4 h-4" style={{ color: 'var(--text-secondary)' }} />
    }
  }

  const badgeStyle = (): React.CSSProperties => {
    switch (state.status) {
      case 'running':
        return {
          background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
          color: 'var(--accent-blue)',
          border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
        }
      case 'completed':
        return {
          background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
          color: 'var(--accent-green)',
          border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
        }
      case 'error':
        return {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      default:
        return {
          background: 'color-mix(in srgb, var(--text-secondary) 10%, transparent)',
          color: 'var(--text-secondary)',
          border: '1px solid color-mix(in srgb, var(--text-secondary) 20%, transparent)',
        }
    }
  }

  return (
    <div className="flex items-center justify-between py-1.5 px-2 rounded" style={{ background: 'var(--bg-surface)' }}>
      <div className="flex items-center gap-2">
        {icon()}
        <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
          {domainLabel(state.domain)}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {state.duration_ms !== undefined && (
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {formatDuration(state.duration_ms)}
          </span>
        )}
        <Badge style={badgeStyle()}>{state.status}</Badge>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// HypothesisCard — single ranked hypothesis
// ---------------------------------------------------------------------------

function HypothesisCard({ hypothesis }: { hypothesis: Hypothesis }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div
      className="rounded border p-3 cursor-pointer"
      style={{
        background: 'var(--bg-surface)',
        borderColor: 'var(--border)',
      }}
      onClick={() => setExpanded(v => !v)}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)',
              color: 'var(--accent-blue)',
            }}
          >
            {hypothesis.rank}
          </span>
          <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
            {hypothesis.description}
          </span>
        </div>
        <Badge
          style={{
            background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
            color: 'var(--accent-yellow)',
            border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
          }}
        >
          {confidencePct(hypothesis.confidence)}
        </Badge>
      </div>
      {expanded && hypothesis.evidence.length > 0 && (
        <ul className="mt-2 pl-7 space-y-1">
          {hypothesis.evidence.map((e, i) => (
            <li key={i} className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {e}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ParallelInvestigationPanel — main export
// ---------------------------------------------------------------------------

export function ParallelInvestigationPanel({
  domains,
  investigationId,
  domainResults = {},
  synthesis,
  hypotheses = [],
  totalDurationMs,
}: ParallelInvestigationPanelProps) {
  const [domainStates, setDomainStates] = useState<DomainState[]>(() =>
    domains.map(d => ({ domain: d, status: 'running' as DomainStatus }))
  )

  // Sync external domainResults into local state
  useEffect(() => {
    setDomainStates(prev =>
      prev.map(ds => {
        const result = domainResults[ds.domain]
        if (!result) return ds
        const status: DomainStatus =
          result.status === 'completed' ? 'completed'
          : result.status === 'error' ? 'error'
          : ds.status
        return { ...ds, status, duration_ms: result.duration_ms }
      })
    )
  }, [domainResults])

  const allDone = domainStates.every(ds => ds.status === 'completed' || ds.status === 'error')
  const completedCount = domainStates.filter(ds => ds.status === 'completed').length

  // Routing explanation shown in the panel header
  const routingNote = `Dispatching to [${domains.map(domainLabel).join(', ')}] — parallel investigation across ${domains.length} domain${domains.length > 1 ? 's' : ''}.`

  return (
    <Card style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}>
      <CardContent className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {!allDone && <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--accent-blue)' }} />}
            {allDone && <CheckCircle2 className="w-4 h-4" style={{ color: 'var(--accent-green)' }} />}
            <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
              Parallel Investigation
            </span>
            <Badge
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                color: 'var(--accent-blue)',
                border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
                fontSize: '10px',
              }}
            >
              {completedCount}/{domains.length} domains
            </Badge>
          </div>
          {totalDurationMs !== undefined && (
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Total: {formatDuration(totalDurationMs)}
            </span>
          )}
        </div>

        {/* Routing note */}
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          {routingNote}
        </p>

        {/* Per-domain progress rows */}
        <div className="space-y-1.5">
          {domainStates.map(ds => (
            <DomainRow key={ds.domain} state={ds} />
          ))}
        </div>

        {/* Synthesis — shown when all domains complete */}
        {allDone && synthesis && (
          <div
            className="rounded p-3 mt-2"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 8%, transparent)',
              border: '1px solid color-mix(in srgb, var(--accent-blue) 20%, transparent)',
            }}
          >
            <p className="text-xs font-semibold mb-1" style={{ color: 'var(--accent-blue)' }}>
              Root-Cause Synthesis
            </p>
            <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>
              {synthesis}
            </p>
          </div>
        )}

        {/* Hypotheses */}
        {allDone && hypotheses.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
              Ranked Hypotheses — click to expand evidence
            </p>
            {hypotheses.map(h => (
              <HypothesisCard key={h.rank} hypothesis={h} />
            ))}
          </div>
        )}

        {/* Investigation ID — for traceability */}
        <p className="text-xs" style={{ color: 'var(--text-secondary)', opacity: 0.6 }}>
          Investigation ID: {investigationId}
        </p>
      </CardContent>
    </Card>
  )
}

export default ParallelInvestigationPanel
