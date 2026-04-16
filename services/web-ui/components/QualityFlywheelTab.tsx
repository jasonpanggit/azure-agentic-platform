'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  TrendingUp,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  BookOpen,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface QualityMetrics {
  mttr_p50_min: number | null
  mttr_p95_min: number | null
  auto_remediation_rate: number | null
  noise_ratio: number | null
  sop_count_scored: number
  avg_sop_effectiveness: number | null
  error?: string
}

interface SopEffectivenessItem {
  sop_id: string
  total_incidents: number
  resolved_count: number
  effectiveness_score: number
  window_days: number
}

interface FeedbackRecord {
  feedback_id: string
  incident_id: string
  action_type: 'approve' | 'reject' | 'resolved' | 'degraded'
  operator_id: string | null
  operator_decision: string | null
  verification_outcome: string | null
  response_quality_score: number | null
  sop_id: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type StatusLevel = 'good' | 'warning' | 'poor'

function kpiStatus(
  value: number | null,
  { goodBelow, warnBelow }: { goodBelow: number; warnBelow: number }
): StatusLevel {
  if (value === null) return 'poor'
  if (value < goodBelow) return 'good'
  if (value < warnBelow) return 'warning'
  return 'poor'
}

function rateStatus(
  value: number | null,
  { goodAbove, warnAbove }: { goodAbove: number; warnAbove: number }
): StatusLevel {
  if (value === null) return 'poor'
  if (value >= goodAbove) return 'good'
  if (value >= warnAbove) return 'warning'
  return 'poor'
}

const STATUS_STYLES: Record<StatusLevel, React.CSSProperties> = {
  good: {
    background: 'color-mix(in srgb, var(--accent-green) 12%, transparent)',
    color: 'var(--accent-green)',
    border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
  },
  warning: {
    background: 'color-mix(in srgb, var(--accent-yellow) 12%, transparent)',
    color: 'var(--accent-yellow)',
    border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
  },
  poor: {
    background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
    color: 'var(--accent-red)',
    border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
  },
}

function StatusBadge({ level, label }: { level: StatusLevel; label: string }) {
  return <Badge style={STATUS_STYLES[level]}>{label}</Badge>
}

function fmt(v: number | null, decimals = 1): string {
  if (v === null) return '—'
  return v.toFixed(decimals)
}

function fmtPct(v: number | null): string {
  if (v === null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

interface KpiCardProps {
  label: string
  value: string
  status: StatusLevel
  description: string
}

function KpiCard({ label, value, status, description }: KpiCardProps) {
  return (
    <Card
      style={{
        border: `1px solid ${status === 'good'
          ? 'color-mix(in srgb, var(--accent-green) 30%, transparent)'
          : status === 'warning'
          ? 'color-mix(in srgb, var(--accent-yellow) 30%, transparent)'
          : 'color-mix(in srgb, var(--accent-red) 30%, transparent)'}`,
        background: 'var(--bg-surface)',
      }}
    >
      <CardContent className="p-4">
        <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
          {label}
        </p>
        <p className="text-2xl font-bold mb-1" style={{ color: 'var(--text-primary)' }}>
          {value}
        </p>
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          {description}
        </p>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Action icon
// ---------------------------------------------------------------------------

function ActionIcon({ actionType }: { actionType: string }) {
  switch (actionType) {
    case 'approve':
      return <ThumbsUp className="h-4 w-4" style={{ color: 'var(--accent-green)' }} />
    case 'reject':
      return <ThumbsDown className="h-4 w-4" style={{ color: 'var(--accent-red)' }} />
    case 'resolved':
      return <CheckCircle className="h-4 w-4" style={{ color: 'var(--accent-green)' }} />
    case 'degraded':
      return <AlertTriangle className="h-4 w-4" style={{ color: 'var(--accent-yellow)' }} />
    default:
      return <Clock className="h-4 w-4" style={{ color: 'var(--text-secondary)' }} />
  }
}

// ---------------------------------------------------------------------------
// QualityFlywheelTab
// ---------------------------------------------------------------------------

export function QualityFlywheelTab() {
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null)
  const [sopItems, setSopItems] = useState<SopEffectivenessItem[]>([])
  const [feedback, setFeedback] = useState<FeedbackRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [metricsRes, sopRes, feedbackRes] = await Promise.all([
        fetch('/api/proxy/quality/metrics'),
        fetch('/api/proxy/quality/sop-effectiveness'),
        fetch('/api/proxy/quality/feedback'),
      ])

      if (!metricsRes.ok) throw new Error(`Metrics fetch failed: ${metricsRes.status}`)
      const metricsData = await metricsRes.json()
      setMetrics(metricsData)

      const sopData = await sopRes.json()
      setSopItems(sopData?.sop_effectiveness ?? [])

      const feedbackData = await feedbackRes.json()
      setFeedback((feedbackData?.feedback ?? []).slice(0, 10))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load quality data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5 * 60 * 1000) // 5 min auto-refresh
    return () => clearInterval(interval)
  }, [load])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            AIOps Quality Flywheel
          </h2>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
          style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
        >
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert>
          <AlertDescription style={{ color: 'var(--accent-red)' }}>{error}</AlertDescription>
        </Alert>
      )}

      {/* KPI Cards */}
      {loading && !metrics ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            label="MTTR P50"
            value={metrics?.mttr_p50_min != null ? `${fmt(metrics.mttr_p50_min)}m` : '—'}
            status={kpiStatus(metrics?.mttr_p50_min ?? null, { goodBelow: 30, warnBelow: 60 })}
            description="Median time to resolve"
          />
          <KpiCard
            label="MTTR P95"
            value={metrics?.mttr_p95_min != null ? `${fmt(metrics.mttr_p95_min)}m` : '—'}
            status={kpiStatus(metrics?.mttr_p95_min ?? null, { goodBelow: 120, warnBelow: 240 })}
            description="95th percentile MTTR"
          />
          <KpiCard
            label="Auto-Remediation Rate"
            value={fmtPct(metrics?.auto_remediation_rate ?? null)}
            status={rateStatus(metrics?.auto_remediation_rate ?? null, { goodAbove: 0.6, warnAbove: 0.4 })}
            description="Approvals / total decisions (30d)"
          />
          <KpiCard
            label="Noise Ratio"
            value={fmtPct(metrics?.noise_ratio ?? null)}
            status={kpiStatus(metrics?.noise_ratio ?? null, { goodBelow: 0.1, warnBelow: 0.25 })}
            description="Rejections / total decisions (30d)"
          />
        </div>
      )}

      {/* SOP Effectiveness Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <div
          className="px-4 py-3 flex items-center gap-2"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <BookOpen className="h-4 w-4" style={{ color: 'var(--text-secondary)' }} />
          <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            SOP Effectiveness
          </h3>
          {metrics && (
            <span className="text-xs ml-auto" style={{ color: 'var(--text-secondary)' }}>
              {metrics.sop_count_scored} SOPs scored · avg{' '}
              {fmtPct(metrics.avg_sop_effectiveness ?? null)}
            </span>
          )}
        </div>

        {loading && sopItems.length === 0 ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-8 rounded" />
            ))}
          </div>
        ) : sopItems.length === 0 ? (
          <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>
            <BookOpen className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">No SOP effectiveness data yet.</p>
            <p className="text-xs mt-1">
              Scores are computed once incidents reference SOPs and outcomes are recorded.
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow style={{ borderColor: 'var(--border)' }}>
                <TableHead style={{ color: 'var(--text-secondary)' }}>SOP</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Incidents</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Resolved %</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Score</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sopItems.map((sop) => {
                const pct = sop.effectiveness_score
                const level: StatusLevel = pct >= 0.75 ? 'good' : pct >= 0.5 ? 'warning' : 'poor'
                return (
                  <TableRow key={sop.sop_id} style={{ borderColor: 'var(--border)' }}>
                    <TableCell
                      className="font-mono text-xs"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {sop.sop_id}
                    </TableCell>
                    <TableCell style={{ color: 'var(--text-secondary)' }}>
                      {sop.total_incidents}
                    </TableCell>
                    <TableCell style={{ color: 'var(--text-secondary)' }}>
                      {sop.total_incidents > 0
                        ? `${sop.resolved_count} / ${sop.total_incidents}`
                        : '—'}
                    </TableCell>
                    <TableCell style={{ color: 'var(--text-primary)' }}>
                      {fmtPct(pct)}
                    </TableCell>
                    <TableCell>
                      {level === 'poor' ? (
                        <Badge
                          style={{
                            background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                            color: 'var(--accent-red)',
                            border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
                          }}
                        >
                          Needs Review
                        </Badge>
                      ) : (
                        <StatusBadge
                          level={level}
                          label={level === 'good' ? 'Effective' : 'Marginal'}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Recent Feedback Timeline */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <div
          className="px-4 py-3"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Recent Feedback
          </h3>
        </div>

        {loading && feedback.length === 0 ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 rounded" />
            ))}
          </div>
        ) : feedback.length === 0 ? (
          <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>
            <Clock className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">No feedback events recorded yet.</p>
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {feedback.map((fb) => (
              <div key={fb.feedback_id} className="flex items-center gap-3 px-4 py-3">
                <ActionIcon actionType={fb.action_type} />
                <div className="flex-1 min-w-0">
                  <span
                    className="text-xs font-mono"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {fb.incident_id}
                  </span>
                  <span
                    className="ml-2 text-xs"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {fb.action_type}
                  </span>
                  {fb.verification_outcome && (
                    <span
                      className="ml-2 text-xs"
                      style={{
                        color:
                          fb.verification_outcome === 'RESOLVED'
                            ? 'var(--accent-green)'
                            : fb.verification_outcome === 'DEGRADED'
                            ? 'var(--accent-red)'
                            : 'var(--text-secondary)',
                      }}
                    >
                      → {fb.verification_outcome}
                    </span>
                  )}
                </div>
                <span className="text-xs shrink-0" style={{ color: 'var(--text-secondary)' }}>
                  {timeAgo(fb.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
