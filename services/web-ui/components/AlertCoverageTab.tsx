'use client'

import { useState, useEffect, useCallback } from 'react'
import { Bell, RefreshCw, AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// ── Types ─────────────────────────────────────────────────────────────────────

interface AlertCoverageGap {
  readonly gap_id: string
  readonly subscription_id: string
  readonly resource_type: string
  readonly resource_count: number
  readonly alert_rule_count: number
  readonly severity: 'critical' | 'high' | 'medium'
  readonly recommendation: string
  readonly scanned_at: string
}

interface AlertCoverageSummary {
  readonly total_gaps: number
  readonly critical_gaps: number
  readonly high_gaps: number
  readonly medium_gaps: number
  readonly subscriptions_with_gaps: number
  readonly overall_coverage_pct: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityColor(severity: string): string {
  switch (severity) {
    case 'critical': return 'var(--accent-red)'
    case 'high':     return 'var(--accent-orange)'
    case 'medium':   return 'var(--accent-yellow)'
    default:         return 'var(--text-muted)'
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = severityColor(severity)
  return (
    <Badge
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 40%, transparent)`,
      }}
    >
      {severity.toUpperCase()}
    </Badge>
  )
}

function groupBySubscription(gaps: AlertCoverageGap[]): Record<string, AlertCoverageGap[]> {
  return gaps.reduce<Record<string, AlertCoverageGap[]>>((acc, gap) => {
    const sub = gap.subscription_id
    return { ...acc, [sub]: [...(acc[sub] ?? []), gap] }
  }, {})
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AlertCoverageTab({ subscriptionId }: { subscriptionId?: string }) {
  const [summary, setSummary] = useState<AlertCoverageSummary | null>(null)
  const [gaps, setGaps] = useState<AlertCoverageGap[]>([])
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<string>('ALL')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (subscriptionId) params.set('subscription_id', subscriptionId)
      if (severityFilter !== 'ALL') params.set('severity', severityFilter.toLowerCase())

      const [summaryRes, gapsRes] = await Promise.all([
        fetch('/api/proxy/alert-coverage/summary'),
        fetch(`/api/proxy/alert-coverage/gaps?${params}`),
      ])

      if (summaryRes.ok) {
        setSummary(await summaryRes.json())
      }
      if (gapsRes.ok) {
        const data = await gapsRes.json()
        setGaps(data.gaps ?? [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load alert coverage data')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId, severityFilter])

  useEffect(() => {
    void fetchData()
    const id = setInterval(() => { void fetchData() }, 10 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      const params = new URLSearchParams()
      if (subscriptionId) params.set('subscription_id', subscriptionId)
      await fetch(`/api/proxy/alert-coverage/scan?${params}`, { method: 'POST' })
      await fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const grouped = groupBySubscription(gaps)

  return (
    <div className="flex flex-col gap-6 p-4" style={{ color: 'var(--text-primary)' }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-lg font-semibold">Alert Rule Coverage Audit</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchData()}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => void handleScan()} disabled={scanning}>
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {error && (
        <div
          className="rounded p-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          {error}
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Total Gaps',      value: summary.total_gaps,              color: 'var(--text-primary)' },
            { label: 'Critical',        value: summary.critical_gaps,           color: 'var(--accent-red)' },
            { label: 'High',            value: summary.high_gaps,               color: 'var(--accent-orange)' },
            { label: 'Subs w/ Gaps',    value: summary.subscriptions_with_gaps, color: 'var(--accent-yellow)' },
          ].map(({ label, value, color }) => (
            <div
              key={label}
              className="rounded-lg border p-3 text-center"
              style={{ borderColor: 'var(--border)', background: 'var(--bg-canvas)' }}
            >
              <div className="text-2xl font-bold" style={{ color }}>{value}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Coverage progress bar */}
      {summary && (
        <div className="space-y-1">
          <div className="flex justify-between text-sm">
            <span style={{ color: 'var(--text-muted)' }}>Overall Alert Coverage</span>
            <span
              style={{
                color: summary.overall_coverage_pct >= 80
                  ? 'var(--accent-green)'
                  : 'var(--accent-red)',
              }}
            >
              {summary.overall_coverage_pct}%
            </span>
          </div>
          <div style={{ background: 'var(--border)', borderRadius: '4px', height: '8px', overflow: 'hidden' }}>
            <div style={{ width: `${summary.overall_coverage_pct}%`, height: '100%', background: summary.overall_coverage_pct >= 80 ? 'var(--accent-green)' : 'var(--accent-red)', transition: 'width 0.3s' }} />
          </div>
        </div>
      )}

      {/* Filter */}
      <div className="flex gap-3">
        <Select value={severityFilter} onValueChange={setSeverityFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All Severities</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="medium">Medium</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Gaps grouped by subscription */}
      {loading && (
        <div className="text-center py-8" style={{ color: 'var(--text-muted)' }}>Loading…</div>
      )}
      {!loading && gaps.length === 0 && (
        <div className="text-center py-8" style={{ color: 'var(--text-muted)' }}>
          No coverage gaps found. Run a scan to populate data.
        </div>
      )}

      {Object.entries(grouped).map(([sub, subGaps]) => (
        <div key={sub}>
          <div
            className="text-xs font-mono mb-2 px-1"
            style={{ color: 'var(--text-muted)' }}
          >
            Subscription: {sub}
          </div>
          <div className="rounded-lg border overflow-auto" style={{ borderColor: 'var(--border)' }}>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Resource Type</TableHead>
                  <TableHead className="text-right">Count</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Recommendation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {subGaps.map((gap) => (
                  <TableRow key={gap.gap_id}>
                    <TableCell className="font-medium">{gap.resource_type}</TableCell>
                    <TableCell className="text-right">{gap.resource_count}</TableCell>
                    <TableCell>
                      <SeverityBadge severity={gap.severity} />
                    </TableCell>
                    <TableCell className="text-sm" style={{ color: 'var(--text-muted)', maxWidth: '400px' }}>
                      {gap.recommendation}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      ))}
    </div>
  )
}
