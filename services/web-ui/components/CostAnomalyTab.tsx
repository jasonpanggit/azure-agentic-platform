'use client'

import { useState, useEffect, useCallback } from 'react'
import { TrendingUp, RefreshCw, CheckCircle, AlertTriangle, XCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CostAnomaly {
  anomaly_id: string
  subscription_id: string
  service_name: string
  date: string
  cost_usd: number
  baseline_usd: number
  z_score: number
  severity: 'warning' | 'critical'
  pct_change: number
  description: string
  detected_at: string
}

interface TopSpender {
  service: string
  cost: number
  change_pct: number
}

interface CostSummary {
  total_anomalies: number
  critical_count: number
  warning_count: number
  top_spenders: TopSpender[]
}

interface CostAnomalyTabProps {
  subscriptions?: string[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatUsd(value: number): string {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function formatPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function SeverityBadge({ severity }: { severity: 'warning' | 'critical' }) {
  if (severity === 'critical') {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold"
        style={{
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
        }}
      >
        <XCircle className="h-3 w-3" />
        Critical
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold"
      style={{
        background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: 'var(--accent-yellow)',
      }}
    >
      <AlertTriangle className="h-3 w-3" />
      Warning
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CostAnomalyTab({ subscriptions = [] }: CostAnomalyTabProps) {
  const [selectedSub, setSelectedSub] = useState<string>('all')
  const [anomalies, setAnomalies] = useState<CostAnomaly[]>([])
  const [summary, setSummary] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const subParam = selectedSub !== 'all' ? `?subscription_id=${encodeURIComponent(selectedSub)}` : ''

      const [anomaliesRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/cost/anomalies${subParam}`),
        fetch(`/api/proxy/cost/summary${subParam}`),
      ])

      if (!anomaliesRes.ok || !summaryRes.ok) {
        throw new Error(`API error: anomalies=${anomaliesRes.status} summary=${summaryRes.status}`)
      }

      const [anomaliesData, summaryData] = await Promise.all([
        anomaliesRes.json(),
        summaryRes.json(),
      ])

      setAnomalies(anomaliesData.anomalies ?? [])
      setSummary(summaryData)
      setLastRefreshed(new Date())
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [selectedSub])

  // Initial load + subscription change
  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Auto-refresh every 10 minutes
  useEffect(() => {
    const interval = setInterval(fetchData, 10 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleRunScan = async () => {
    setScanning(true)
    try {
      const res = await fetch('/api/proxy/cost/scan', { method: 'POST' })
      if (res.ok) {
        // Poll after a short delay to pick up fresh results
        setTimeout(fetchData, 3000)
      }
    } catch {
      // Non-fatal — user can retry
    } finally {
      setScanning(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Skeleton
  // ---------------------------------------------------------------------------
  if (loading) {
    return (
      <div className="space-y-4">
        {/* Summary strip skeleton */}
        <div className="grid grid-cols-3 gap-4">
          {[0, 1, 2].map(i => (
            <Card key={i} className="p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
              <Skeleton className="h-4 w-24 mb-2" />
              <Skeleton className="h-7 w-16" />
            </Card>
          ))}
        </div>
        {/* Anomaly card skeletons */}
        {[0, 1, 2].map(i => (
          <Card key={i} className="p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <Skeleton className="h-4 w-40 mb-2" />
            <Skeleton className="h-3 w-full mb-1" />
            <Skeleton className="h-3 w-3/4" />
          </Card>
        ))}
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const topSpender = summary?.top_spenders?.[0]

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Cost Anomalies
          </h2>
          {lastRefreshed && (
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Updated {lastRefreshed.toLocaleTimeString()}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {subscriptions.length > 1 && (
            <Select value={selectedSub} onValueChange={setSelectedSub}>
              <SelectTrigger className="w-48 h-8 text-xs" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
                <SelectValue placeholder="All subscriptions" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All subscriptions</SelectItem>
                {subscriptions.map(sub => (
                  <SelectItem key={sub} value={sub}>{sub}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          <Button
            size="sm"
            variant="outline"
            onClick={fetchData}
            disabled={loading}
            className="h-8 text-xs gap-1"
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>

          <Button
            size="sm"
            onClick={handleRunScan}
            disabled={scanning}
            className="h-8 text-xs gap-1"
            style={{ background: 'var(--accent-blue)', color: '#fff', border: 'none' }}
          >
            <TrendingUp className="h-3.5 w-3.5" />
            {scanning ? 'Scanning…' : 'Run Scan'}
          </Button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            border: '1px solid var(--accent-red)',
            color: 'var(--accent-red)',
          }}
        >
          Failed to load cost data: {error}
        </div>
      )}

      {/* Summary strip */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Card
            className="p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
              Anomalies This Week
            </p>
            <p className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
              {summary.total_anomalies}
            </p>
            <div className="flex gap-2 mt-1">
              {summary.critical_count > 0 && (
                <span className="text-xs" style={{ color: 'var(--accent-red)' }}>
                  {summary.critical_count} critical
                </span>
              )}
              {summary.warning_count > 0 && (
                <span className="text-xs" style={{ color: 'var(--accent-yellow)' }}>
                  {summary.warning_count} warning
                </span>
              )}
            </div>
          </Card>

          <Card
            className="p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
              Top Spending Service
            </p>
            {topSpender ? (
              <>
                <p className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                  {topSpender.service}
                </p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                  {formatUsd(topSpender.cost)} &nbsp;
                  <span style={{ color: topSpender.change_pct > 0 ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                    {formatPct(topSpender.change_pct)}
                  </span>
                </p>
              </>
            ) : (
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>—</p>
            )}
          </Card>

          <Card
            className="p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
              Detection Method
            </p>
            <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
              Z-Score (σ)
            </p>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
              Warning ≥ 2.5σ · Critical &gt; 3.5σ
            </p>
          </Card>
        </div>
      )}

      {/* Anomaly list */}
      {anomalies.length === 0 && !loading && !error ? (
        <Card
          className="flex flex-col items-center justify-center py-16"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          <CheckCircle className="h-10 w-10 mb-3" style={{ color: 'var(--accent-green)' }} />
          <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
            No cost anomalies detected
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
            All services are spending within normal range.
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {anomalies.map(anomaly => (
            <Card
              key={anomaly.anomaly_id}
              className="p-4"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="font-semibold text-sm truncate" style={{ color: 'var(--text-primary)' }}>
                      {anomaly.service_name}
                    </span>
                    <SeverityBadge severity={anomaly.severity} />
                    <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {anomaly.date}
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {anomaly.description}
                  </p>
                </div>

                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                    {formatUsd(anomaly.cost_usd)}
                  </span>
                  <span
                    className="text-xs font-medium"
                    style={{
                      color: anomaly.pct_change > 0 ? 'var(--accent-red)' : 'var(--accent-green)',
                    }}
                  >
                    {formatPct(anomaly.pct_change)} vs baseline
                  </span>
                  <span
                    className="text-xs px-1.5 py-0.5 rounded font-mono"
                    style={{
                      background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                      color: 'var(--accent-blue)',
                    }}
                  >
                    z={anomaly.z_score.toFixed(2)}σ
                  </span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
