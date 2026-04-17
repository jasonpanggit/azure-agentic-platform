'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { RefreshCw, ShieldAlert, AlertTriangle, Info } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DefenderAlert {
  alert_id: string
  subscription_id: string
  display_name: string
  description: string
  severity: string
  status: string
  resource_ids: string[]
  generated_at: string
  remediation_steps: string[]
  captured_at: string
}

interface DefenderRecommendation {
  rec_id: string
  subscription_id: string
  resource_group: string
  display_name: string
  severity: string
  description: string
  remediation: string
  resource_id: string
  category: string
  captured_at: string
}

interface DefenderSummary {
  alert_counts_by_severity: Record<string, number>
  recommendation_counts_by_severity: Record<string, number>
  secure_score_estimate: number | null
  top_affected_resources: { resource_id: string; alert_count: number }[]
  total_alerts: number
  total_recommendations: number
}

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

function severityStyle(severity: string): { background: string; color: string; border: string } {
  switch (severity.toLowerCase()) {
    case 'high':
      return {
        background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
        color: 'var(--accent-red)',
        border: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
      }
    case 'medium':
      return {
        background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: 'var(--accent-yellow)',
        border: 'color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
      }
    case 'low':
    case 'informational':
      return {
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
        border: 'color-mix(in srgb, var(--accent-blue) 30%, transparent)',
      }
    default:
      return {
        background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
        color: 'var(--text-primary)',
        border: 'transparent',
      }
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const style = severityStyle(severity)
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border"
      style={style}
    >
      {severity}
    </span>
  )
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border"
      style={{
        background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
        color: 'var(--accent-blue)',
        border: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)',
      }}
    >
      {category}
    </span>
  )
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function truncateResourceId(id: string, maxLen = 60): string {
  if (!id) return '—'
  if (id.length <= maxLen) return id
  const parts = id.split('/')
  return '…/' + parts.slice(-3).join('/')
}

// ---------------------------------------------------------------------------
// Summary strip
// ---------------------------------------------------------------------------

function SummaryStrip({ summary, loading }: { summary: DefenderSummary | null; loading: boolean }) {
  const counts = summary?.alert_counts_by_severity ?? {}
  const recCounts = summary?.recommendation_counts_by_severity ?? {}

  const tiles = [
    { label: 'High Alerts', value: counts['High'] ?? 0, accent: 'var(--accent-red)' },
    { label: 'Medium Alerts', value: counts['Medium'] ?? 0, accent: 'var(--accent-yellow)' },
    { label: 'Low Alerts', value: counts['Low'] ?? 0, accent: 'var(--accent-blue)' },
    { label: 'High Recs', value: recCounts['High'] ?? 0, accent: 'var(--accent-red)' },
    { label: 'Medium Recs', value: recCounts['Medium'] ?? 0, accent: 'var(--accent-yellow)' },
  ]

  return (
    <div className="flex flex-wrap gap-3 mb-4">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="flex flex-col items-center rounded-lg px-4 py-2 min-w-[90px]"
          style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
        >
          {loading ? (
            <Skeleton className="h-6 w-10 mb-1" />
          ) : (
            <span className="text-xl font-bold" style={{ color: t.accent }}>
              {t.value}
            </span>
          )}
          <span className="text-xs" style={{ color: 'var(--text-primary)', opacity: 0.7 }}>
            {t.label}
          </span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Alerts sub-tab
// ---------------------------------------------------------------------------

function AlertsTable({ alerts, loading }: { alerts: DefenderAlert[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="space-y-2 mt-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (alerts.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center py-16 gap-2"
        style={{ color: 'var(--text-primary)', opacity: 0.5 }}
      >
        <ShieldAlert className="w-10 h-10" />
        <p className="text-sm">No active alerts found</p>
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Alert</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Resources</TableHead>
          <TableHead>Generated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {alerts.map((alert) => (
          <TableRow key={alert.alert_id}>
            <TableCell>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="font-medium cursor-help" style={{ color: 'var(--text-primary)' }}>
                      {alert.display_name}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="text-xs">{alert.description || 'No description'}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </TableCell>
            <TableCell>
              <SeverityBadge severity={alert.severity} />
            </TableCell>
            <TableCell>
              <span className="text-xs" style={{ color: 'var(--text-primary)', opacity: 0.8 }}>
                {alert.status}
              </span>
            </TableCell>
            <TableCell>
              <span className="text-xs" style={{ color: 'var(--text-primary)', opacity: 0.7 }}>
                {alert.resource_ids.length} resource{alert.resource_ids.length !== 1 ? 's' : ''}
              </span>
            </TableCell>
            <TableCell>
              <span className="text-xs" style={{ color: 'var(--text-primary)', opacity: 0.7 }}>
                {formatDate(alert.generated_at)}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// ---------------------------------------------------------------------------
// Recommendations sub-tab
// ---------------------------------------------------------------------------

function RecommendationsTable({
  recommendations,
  loading,
}: {
  recommendations: DefenderRecommendation[]
  loading: boolean
}) {
  if (loading) {
    return (
      <div className="space-y-2 mt-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (recommendations.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center py-16 gap-2"
        style={{ color: 'var(--text-primary)', opacity: 0.5 }}
      >
        <AlertTriangle className="w-10 h-10" />
        <p className="text-sm">No unhealthy recommendations found</p>
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Recommendation</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Category</TableHead>
          <TableHead>Resource</TableHead>
          <TableHead>Remediation</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {recommendations.map((rec) => (
          <TableRow key={rec.rec_id}>
            <TableCell>
              <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
                {rec.display_name}
              </span>
            </TableCell>
            <TableCell>
              <SeverityBadge severity={rec.severity} />
            </TableCell>
            <TableCell>
              <CategoryBadge category={rec.category || 'General'} />
            </TableCell>
            <TableCell>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span
                      className="text-xs cursor-help font-mono"
                      style={{ color: 'var(--text-primary)', opacity: 0.7 }}
                    >
                      {truncateResourceId(rec.resource_id)}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p className="text-xs break-all max-w-xs">{rec.resource_id || '—'}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </TableCell>
            <TableCell>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Info
                        className="w-4 h-4 cursor-help"
                        style={{ color: 'var(--accent-blue)' }}
                      />
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="text-xs">{rec.remediation || 'No remediation steps available'}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// ---------------------------------------------------------------------------
// Main DefenderTab component
// ---------------------------------------------------------------------------

type SubTab = 'alerts' | 'recommendations'

export function DefenderTab() {
  const [subTab, setSubTab] = useState<SubTab>('alerts')
  const [alerts, setAlerts] = useState<DefenderAlert[]>([])
  const [recommendations, setRecommendations] = useState<DefenderRecommendation[]>([])
  const [summary, setSummary] = useState<DefenderSummary | null>(null)
  const [loadingAlerts, setLoadingAlerts] = useState(false)
  const [loadingRecs, setLoadingRecs] = useState(false)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchSummary = useCallback(async () => {
    setLoadingSummary(true)
    try {
      const res = await fetch('/api/proxy/defender/summary')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSummary(data)
    } catch (err) {
      // summary strip degrades gracefully
    } finally {
      setLoadingSummary(false)
    }
  }, [])

  const fetchAlerts = useCallback(async () => {
    setLoadingAlerts(true)
    setError(null)
    try {
      const res = await fetch('/api/proxy/defender/alerts?limit=50')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setAlerts(data.alerts ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load alerts')
    } finally {
      setLoadingAlerts(false)
    }
  }, [])

  const fetchRecommendations = useCallback(async () => {
    setLoadingRecs(true)
    setError(null)
    try {
      const res = await fetch('/api/proxy/defender/recommendations')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRecommendations(data.recommendations ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load recommendations')
    } finally {
      setLoadingRecs(false)
    }
  }, [])

  const triggerScan = useCallback(async () => {
    setScanning(true)
    try {
      await fetch('/api/proxy/defender/scan', { method: 'POST' })
      // After scan queued, re-fetch after a short delay
      setTimeout(() => {
        fetchAlerts()
        fetchRecommendations()
        fetchSummary()
      }, 3000)
    } catch {
      // non-fatal
    } finally {
      setScanning(false)
    }
  }, [fetchAlerts, fetchRecommendations, fetchSummary])

  // Initial load
  useEffect(() => {
    fetchAlerts()
    fetchRecommendations()
    fetchSummary()
  }, [fetchAlerts, fetchRecommendations, fetchSummary])

  // 5-minute auto-refresh
  useEffect(() => {
    const interval = setInterval(() => {
      fetchAlerts()
      fetchRecommendations()
      fetchSummary()
    }, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchAlerts, fetchRecommendations, fetchSummary])

  const subTabs: { id: SubTab; label: string; count: number }[] = [
    { id: 'alerts', label: 'Alerts', count: alerts.length },
    { id: 'recommendations', label: 'Recommendations', count: recommendations.length },
  ]

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5" style={{ color: 'var(--accent-red)' }} />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Microsoft Defender for Cloud
          </h2>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={triggerScan}
          disabled={scanning}
          className="flex items-center gap-1"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`} />
          {scanning ? 'Scanning…' : 'Refresh'}
        </Button>
      </div>

      {/* Summary strip */}
      <SummaryStrip summary={summary} loading={loadingSummary} />

      {/* Error banner */}
      {error && (
        <div
          className="rounded-md px-3 py-2 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            color: 'var(--accent-red)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
          }}
        >
          {error}
        </div>
      )}

      {/* Sub-tab bar */}
      <div
        className="flex gap-1 rounded-lg p-1 w-fit"
        style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
      >
        {subTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setSubTab(tab.id)}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
            style={
              subTab === tab.id
                ? {
                    background: 'var(--accent-blue)',
                    color: '#fff',
                  }
                : {
                    color: 'var(--text-primary)',
                    opacity: 0.7,
                  }
            }
          >
            {tab.label}
            <span
              className="rounded-full px-1.5 py-0.5 text-xs"
              style={
                subTab === tab.id
                  ? { background: 'rgba(255,255,255,0.2)' }
                  : {
                      background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                      color: 'var(--accent-blue)',
                    }
              }
            >
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* Content */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)', background: 'var(--bg-canvas)' }}
      >
        {subTab === 'alerts' && <AlertsTable alerts={alerts} loading={loadingAlerts} />}
        {subTab === 'recommendations' && (
          <RecommendationsTable recommendations={recommendations} loading={loadingRecs} />
        )}
      </div>
    </div>
  )
}
