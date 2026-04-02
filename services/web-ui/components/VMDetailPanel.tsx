'use client'

import { useState, useEffect, useCallback } from 'react'
import { X, RefreshCw, AlertTriangle, CheckCircle, XCircle, HelpCircle, Activity } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface VMDetail {
  id: string
  name: string
  resource_group: string
  subscription_id: string
  location: string
  size: string
  os_type: string
  os_name: string
  power_state: string
  health_state: string
  health_summary: string | null
  ama_status: string
  tags: Record<string, string>
  active_incidents: ActiveIncident[]
}

interface ActiveIncident {
  incident_id: string
  severity: string
  title?: string
  created_at: string
  status: string
  investigation_status?: string
}

interface Evidence {
  pipeline_status: 'complete' | 'partial' | 'failed' | 'pending'
  collected_at: string | null
  evidence_summary: {
    health_state: string
    recent_changes: RecentChange[]
    metric_anomalies: MetricAnomaly[]
    log_errors: { count: number; sample: string[] }
  } | null
}

interface RecentChange {
  timestamp: string
  operation: string
  caller: string
  status: string
}

interface MetricAnomaly {
  metric_name: string
  current_value: number
  threshold: number
  unit: string
}

interface MetricSeries {
  name: string | null
  unit: string | null
  timeseries: { timestamp: string; average: number | null; maximum: number | null }[]
}

interface VMDetailPanelProps {
  incidentId: string | null          // incident that opened the panel (for evidence lookup)
  resourceId: string | null          // ARM resource ID
  resourceName: string | null        // display name
  onClose: () => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function encodeResourceId(resourceId: string): string {
  // base64url encode without padding (matches Python urlsafe_b64encode().rstrip("="))
  return btoa(resourceId).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

function HealthIcon({ state }: { state: string }) {
  const s = state.toLowerCase()
  if (s === 'available') return <CheckCircle className="h-4 w-4" style={{ color: 'var(--accent-green)' }} />
  if (s === 'degraded') return <AlertTriangle className="h-4 w-4" style={{ color: 'var(--accent-orange)' }} />
  if (s === 'unavailable') return <XCircle className="h-4 w-4" style={{ color: 'var(--accent-red)' }} />
  return <HelpCircle className="h-4 w-4" style={{ color: 'var(--text-muted)' }} />
}

function HealthColor(state: string): string {
  const s = state.toLowerCase()
  if (s === 'available') return 'var(--accent-green)'
  if (s === 'degraded') return 'var(--accent-orange)'
  if (s === 'unavailable') return 'var(--accent-red)'
  return 'var(--text-muted)'
}

function PowerBadge({ state }: { state: string }) {
  const config: Record<string, { label: string; color: string }> = {
    running: { label: 'Running', color: 'var(--accent-green)' },
    stopped: { label: 'Stopped', color: 'var(--accent-yellow)' },
    deallocated: { label: 'Deallocated', color: 'var(--text-muted)' },
  }
  const c = config[state] ?? { label: state, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: `color-mix(in srgb, ${c.color} 15%, transparent)`, color: c.color }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.color }} />
      {c.label}
    </span>
  )
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = severity === 'Sev0' || severity === 'Sev1'
    ? 'var(--accent-red)'
    : severity === 'Sev2'
      ? 'var(--accent-orange)'
      : 'var(--accent-yellow)'
  return (
    <span
      className="text-[10px] font-bold px-1.5 py-0.5 rounded"
      style={{ background: `color-mix(in srgb, ${color} 15%, transparent)`, color }}
    >
      {severity}
    </span>
  )
}

// Simple sparkline using SVG path
function Sparkline({ data, color = 'var(--accent-blue)' }: { data: number[]; color?: string }) {
  if (data.length < 2) return <span className="text-xs" style={{ color: 'var(--text-muted)' }}>No data</span>

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const W = 120, H = 32, pad = 2

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (W - pad * 2)
    const y = H - pad - ((v - min) / range) * (H - pad * 2)
    return `${x},${y}`
  })

  const d = `M ${points.join(' L ')}`

  return (
    <svg width={W} height={H} style={{ overflow: 'visible' }}>
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function VMDetailPanel({ incidentId, resourceId, resourceName, onClose }: VMDetailPanelProps) {
  const [vm, setVM] = useState<VMDetail | null>(null)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [loading, setLoading] = useState(true)
  const [metricsLoading, setMetricsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [timeRange, setTimeRange] = useState<'PT1H' | 'PT6H' | 'PT24H' | 'P7D'>('PT24H')
  const [pollingEvidence, setPollingEvidence] = useState(false)

  // Fetch VM detail
  const fetchVM = useCallback(async () => {
    if (!resourceId) return
    try {
      const encoded = encodeResourceId(resourceId)
      const res = await fetch(`/api/proxy/vms/${encoded}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setVM(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load VM details')
    } finally {
      setLoading(false)
    }
  }, [resourceId])

  // Fetch evidence for incident
  const fetchEvidence = useCallback(async (): Promise<boolean> => {
    if (!incidentId) return true
    try {
      const res = await fetch(`/api/proxy/incidents/${incidentId}/evidence`)
      if (res.status === 202) {
        setPollingEvidence(true)
        return false // still pending
      }
      if (!res.ok) return true // error — stop polling
      const data = await res.json()
      setEvidence(data)
      setPollingEvidence(false)
      return true // done
    } catch {
      setPollingEvidence(false)
      return true
    }
  }, [incidentId])

  // Fetch metrics
  const fetchMetrics = useCallback(async () => {
    if (!resourceId) return
    setMetricsLoading(true)
    try {
      const encoded = encodeResourceId(resourceId)
      const queryParams = new URLSearchParams({
        metrics: 'Percentage CPU,Available Memory Bytes,Disk Read Bytes/sec,Network In Total',
        timespan: timeRange,
        interval: timeRange === 'P7D' ? 'PT1H' : 'PT5M',
      })
      const res = await fetch(`/api/proxy/vms/${encoded}/metrics?${queryParams}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMetrics(data.metrics ?? [])
    } catch {
      setMetrics([])
    } finally {
      setMetricsLoading(false)
    }
  }, [resourceId, timeRange])

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchVM()
    fetchEvidence()
    fetchMetrics()
  }, [resourceId, incidentId, fetchVM, fetchEvidence, fetchMetrics])

  // Poll evidence if still pending
  useEffect(() => {
    if (!pollingEvidence) return
    const timer = setInterval(async () => {
      const done = await fetchEvidence()
      if (done) clearInterval(timer)
    }, 5000)
    return () => clearInterval(timer)
  }, [pollingEvidence, fetchEvidence])

  // Refetch metrics when time range changes
  useEffect(() => {
    if (resourceId) fetchMetrics()
  }, [timeRange, fetchMetrics, resourceId])

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      className="fixed inset-y-0 right-0 z-40 flex flex-col overflow-hidden"
      style={{
        width: '480px',
        background: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border)',
        boxShadow: '-4px 0 24px rgba(0,0,0,0.2)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Activity className="h-4 w-4 flex-shrink-0" style={{ color: 'var(--accent-blue)' }} />
          <span className="font-semibold text-sm truncate" style={{ color: 'var(--text-primary)' }}>
            {resourceName ?? 'VM Detail'}
          </span>
          {vm && <PowerBadge state={vm.power_state} />}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { fetchVM(); fetchEvidence(); }}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-16 rounded animate-pulse" style={{ background: 'var(--bg-subtle)' }} />
            ))}
          </div>
        ) : error ? (
          <div className="p-6 text-center text-sm" style={{ color: 'var(--accent-red)' }}>
            {error}
          </div>
        ) : vm ? (
          <div className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>

            {/* VM Info */}
            <div className="px-4 py-3 space-y-2">
              <div className="flex items-center gap-2">
                <HealthIcon state={vm.health_state} />
                <span className="text-sm font-medium" style={{ color: HealthColor(vm.health_state) }}>
                  {vm.health_state}
                </span>
                {vm.health_summary && (
                  <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    — {vm.health_summary}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {[
                  ['Resource Group', vm.resource_group],
                  ['Location', vm.location],
                  ['Size', vm.size],
                  ['OS', vm.os_name || vm.os_type],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>{label}</div>
                    <div className="text-xs font-mono truncate" style={{ color: 'var(--text-secondary)' }}>{value || '—'}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Evidence section */}
            {incidentId && (
              <div className="px-4 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                  Diagnostic Evidence
                </div>

                {pollingEvidence && !evidence ? (
                  <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Collecting evidence… (typically ~15s)
                  </div>
                ) : evidence?.evidence_summary ? (
                  <div className="space-y-2">
                    {/* Metric anomalies */}
                    {evidence.evidence_summary.metric_anomalies.length > 0 && (
                      <div
                        className="rounded-md p-3"
                        style={{ background: `color-mix(in srgb, var(--accent-orange) 8%, transparent)`, border: '1px solid color-mix(in srgb, var(--accent-orange) 20%, transparent)' }}
                      >
                        <div className="text-xs font-medium mb-1" style={{ color: 'var(--accent-orange)' }}>
                          Metric Anomalies ({evidence.evidence_summary.metric_anomalies.length})
                        </div>
                        {evidence.evidence_summary.metric_anomalies.slice(0, 3).map((a, i) => (
                          <div key={i} className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                            {a.metric_name}: {a.current_value.toFixed(1)} {a.unit} (threshold: {a.threshold})
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Recent changes */}
                    {evidence.evidence_summary.recent_changes.length > 0 && (
                      <div>
                        <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                          Recent Changes (last 2h)
                        </div>
                        {evidence.evidence_summary.recent_changes.slice(0, 5).map((c, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs py-0.5">
                            <span className="font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
                              {new Date(c.timestamp).toLocaleTimeString()}
                            </span>
                            <span className="truncate" style={{ color: 'var(--text-secondary)' }}>
                              {c.operation} — {c.caller}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Log errors */}
                    {evidence.evidence_summary.log_errors.count > 0 && (
                      <div
                        className="rounded-md p-2 text-xs"
                        style={{ background: `color-mix(in srgb, var(--accent-red) 8%, transparent)`, color: 'var(--accent-red)' }}
                      >
                        {evidence.evidence_summary.log_errors.count} log errors detected
                      </div>
                    )}

                    {/* No anomalies */}
                    {evidence.evidence_summary.metric_anomalies.length === 0 &&
                     evidence.evidence_summary.recent_changes.length === 0 &&
                     evidence.evidence_summary.log_errors.count === 0 && (
                      <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        No anomalies detected in the last 2 hours.
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            )}

            {/* Metrics charts */}
            <div className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                  Metrics
                </div>
                <div className="flex gap-1">
                  {(['PT1H', 'PT6H', 'PT24H', 'P7D'] as const).map(r => (
                    <button
                      key={r}
                      onClick={() => setTimeRange(r)}
                      className="text-[10px] px-1.5 py-0.5 rounded cursor-pointer"
                      style={{
                        background: timeRange === r ? 'var(--accent-blue)' : 'var(--bg-subtle)',
                        color: timeRange === r ? 'white' : 'var(--text-secondary)',
                      }}
                    >
                      {r.replace('PT', '').replace('P', '').replace('H', 'h').replace('D', 'd')}
                    </button>
                  ))}
                </div>
              </div>

              {metricsLoading ? (
                <div className="space-y-2">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-10 rounded animate-pulse" style={{ background: 'var(--bg-subtle)' }} />
                  ))}
                </div>
              ) : metrics.length === 0 ? (
                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>No metrics available</div>
              ) : (
                <div className="space-y-3">
                  {metrics.map((m) => {
                    const values = m.timeseries.map(p => p.average ?? 0).filter(v => v > 0)
                    const latest = values[values.length - 1]
                    return (
                      <div key={m.name} className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                            {m.name?.replace('Percentage ', '').replace(' Bytes', 'B').replace('/sec', '/s') ?? '—'}
                          </div>
                          {latest !== undefined && (
                            <div className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>
                              {latest > 1_000_000
                                ? `${(latest / 1_000_000).toFixed(1)} MB`
                                : latest > 1_000
                                  ? `${(latest / 1_000).toFixed(1)} KB`
                                  : `${latest.toFixed(1)} ${m.unit ?? ''}`}
                            </div>
                          )}
                        </div>
                        <Sparkline data={values.slice(-30)} />
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Active incidents */}
            {vm.active_incidents.length > 0 && (
              <div className="px-4 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                  Active Incidents ({vm.active_incidents.length})
                </div>
                <div className="space-y-1.5">
                  {vm.active_incidents.map(inc => (
                    <div
                      key={inc.incident_id}
                      className="flex items-center gap-2 text-xs py-1"
                    >
                      <SeverityBadge severity={inc.severity} />
                      <span className="truncate flex-1" style={{ color: 'var(--text-secondary)' }}>
                        {inc.title ?? inc.incident_id}
                      </span>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {new Date(inc.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Resource-scoped chat placeholder (Phase 3) */}
            <div className="px-4 py-3">
              <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                AI Investigation
              </div>
              <button
                className="w-full text-sm py-2 px-3 rounded-md cursor-not-allowed text-center"
                style={{
                  background: 'var(--bg-subtle)',
                  color: 'var(--text-muted)',
                  border: '1px dashed var(--border)',
                }}
                disabled
                title="Resource-scoped chat coming in Phase 3"
              >
                Investigate with AI — coming in Phase 3
              </button>
            </div>

          </div>
        ) : null}
      </div>
    </div>
  )
}
