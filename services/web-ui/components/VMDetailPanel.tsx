'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { X, RefreshCw, AlertTriangle, CheckCircle, XCircle, HelpCircle, Activity } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'

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

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  approval_id?: string
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

// ── Available metrics catalog ─────────────────────────────────────────────

interface MetricOption {
  name: string       // Azure Monitor metric name
  label: string      // Short display label
  group: string      // CPU | Memory | Disk | Network | Availability
}

const METRIC_CATALOG: MetricOption[] = [
  // CPU
  { name: 'Percentage CPU',              label: 'CPU %',              group: 'CPU' },
  { name: 'CPU Credits Remaining',       label: 'CPU Credits Left',   group: 'CPU' },
  { name: 'CPU Credits Consumed',        label: 'CPU Credits Used',   group: 'CPU' },
  // Memory
  { name: 'Available Memory Bytes',      label: 'Free Memory',        group: 'Memory' },
  // Disk
  { name: 'Disk Read Bytes',             label: 'Disk Read',          group: 'Disk' },
  { name: 'Disk Write Bytes',            label: 'Disk Write',         group: 'Disk' },
  { name: 'Disk Read Operations/Sec',    label: 'Disk Read IOPS',     group: 'Disk' },
  { name: 'Disk Write Operations/Sec',   label: 'Disk Write IOPS',    group: 'Disk' },
  { name: 'OS Disk Queue Depth',         label: 'Disk Queue',         group: 'Disk' },
  { name: 'OS Disk Bandwidth Consumed Percentage', label: 'Disk BW %', group: 'Disk' },
  // Network
  { name: 'Network In Total',            label: 'Net In',             group: 'Network' },
  { name: 'Network Out Total',           label: 'Net Out',            group: 'Network' },
  // Availability
  { name: 'VM Availability Metric',      label: 'Availability',       group: 'Availability' },
]

const DEFAULT_METRICS = [
  'Percentage CPU',
  'Available Memory Bytes',
  'Disk Read Bytes',
  'Disk Write Bytes',
  'Disk Read Operations/Sec',
  'Disk Write Operations/Sec',
  'Network In Total',
  'Network Out Total',
]

// ── Main Component ────────────────────────────────────────────────────────────

export function VMDetailPanel({ incidentId, resourceId, resourceName, onClose }: VMDetailPanelProps) {
  const { instance, accounts } = useMsal()
  const [vm, setVM] = useState<VMDetail | null>(null)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [loading, setLoading] = useState(true)
  const [metricsLoading, setMetricsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [timeRange, setTimeRange] = useState<'PT1H' | 'PT6H' | 'PT24H' | 'P7D'>('PT24H')
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(DEFAULT_METRICS)
  const [metricSelectorOpen, setMetricSelectorOpen] = useState(false)
  const [pollingEvidence, setPollingEvidence] = useState(false)

  // ── Diagnostic settings state ────────────────────────────────────────────
  const [diagConfigured, setDiagConfigured] = useState<boolean | null>(null)
  const [diagEnabling, setDiagEnabling] = useState(false)
  const [diagError, setDiagError] = useState<string | null>(null)

  // ── Chat state ──────────────────────────────────────────────────────────────
  const [chatOpen, setChatOpen] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatStreaming, setChatStreaming] = useState(false)
  const [chatThreadId, setChatThreadId] = useState<string | null>(null)
  // chatRunId is stored for future use (Phase 18 ProposalCard) and reset on panel close
  const [, setChatRunId] = useState<string | null>(null)
  const chatPollRef = useRef<NodeJS.Timeout | null>(null)

  // ── Auth token acquisition ────────────────────────────────────────────────
  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const account = accounts[0]
    if (!account) return null
    try {
      const result = await instance.acquireTokenSilent({ ...gatewayTokenRequest, account })
      return result.accessToken
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ ...gatewayTokenRequest, account })
      }
      return null
    }
  }, [instance, accounts])

  // Fetch VM detail
  const fetchVM = useCallback(async () => {
    if (!resourceId) return
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vms/${encoded}`, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setVM(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load VM details')
    } finally {
      setLoading(false)
    }
  }, [resourceId, getAccessToken])

  // Fetch evidence for incident
  const fetchEvidence = useCallback(async (): Promise<boolean> => {
    if (!incidentId) return true
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/incidents/${incidentId}/evidence`, { headers })
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
  }, [incidentId, getAccessToken])

  // Fetch metrics
  const fetchMetrics = useCallback(async () => {
    if (!resourceId) return
    setMetricsLoading(true)
    try {
      const encoded = encodeResourceId(resourceId)
      const queryParams = new URLSearchParams({
        metrics: selectedMetrics.join(','),
        timespan: timeRange,
        interval: timeRange === 'P7D' ? 'PT1H' : 'PT5M',
      })
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vms/${encoded}/metrics?${queryParams}`, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMetrics(data.metrics ?? [])
    } catch {
      setMetrics([])
    } finally {
      setMetricsLoading(false)
    }
  }, [resourceId, timeRange, selectedMetrics, getAccessToken])

  // ── Diagnostic settings functions ────────────────────────────────────────

  async function fetchDiagSettings() {
    if (!resourceId) return
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vms/${encoded}/diagnostic-settings`, { headers })
      if (!res.ok) return
      const data = await res.json()
      setDiagConfigured(data.configured ?? false)
    } catch {
      // non-fatal — leave diagConfigured as null (unknown)
    }
  }

  async function enableDiagSettings() {
    if (!resourceId || diagEnabling) return
    setDiagEnabling(true)
    setDiagError(null)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vms/${encoded}/diagnostic-settings`, {
        method: 'POST',
        headers,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.error ?? `HTTP ${res.status}`)
      setDiagConfigured(true)
    } catch (err) {
      setDiagError(err instanceof Error ? err.message : 'Failed to enable diagnostic settings')
    } finally {
      setDiagEnabling(false)
    }
  }

  // ── Chat functions ──────────────────────────────────────────────────────────

  function startChatPolling(threadId: string, runId: string) {
    if (chatPollRef.current) clearInterval(chatPollRef.current)

    // Guard against two concurrent interval callbacks both appending a reply
    let appended = false

    chatPollRef.current = setInterval(async () => {
      try {
        const token = await getAccessToken()
        const headers: Record<string, string> = {}
        if (token) headers['Authorization'] = `Bearer ${token}`
        const res = await fetch(
          `/api/proxy/chat/result?thread_id=${encodeURIComponent(threadId)}&run_id=${encodeURIComponent(runId)}`,
          { headers }
        )
        if (!res.ok) {
          clearInterval(chatPollRef.current!)
          setChatStreaming(false)
          return
        }
        const data = await res.json()

        const terminal = ['completed', 'failed', 'cancelled', 'expired']
        if (terminal.includes(data.run_status)) {
          clearInterval(chatPollRef.current!)
          setChatStreaming(false)
          // Only append once — guards against concurrent interval callbacks
          if (!appended) {
            appended = true
            if (data.run_status === 'completed' && data.reply) {
              setChatMessages(prev => [
                ...prev,
                { role: 'assistant', content: data.reply, approval_id: data.approval_id },
              ])
            } else if (data.run_status === 'failed' || data.run_status === 'cancelled' || data.run_status === 'expired') {
              setChatMessages(prev => [
                ...prev,
                { role: 'assistant', content: 'Error: the AI agent run did not complete. Please try again.' },
              ])
            }
          }
        }
      } catch {
        clearInterval(chatPollRef.current!)
        setChatStreaming(false)
      }
    }, 2000)
  }

  async function sendChatMessage(text: string) {
    if (!resourceId || !text.trim() || chatStreaming) return

    const encoded = encodeResourceId(resourceId)
    setChatMessages(prev => [...prev, { role: 'user', content: text }])
    setChatInput('')
    setChatStreaming(true)

    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vms/${encoded}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: text,
          thread_id: chatThreadId,
          incident_id: incidentId,
        }),
      })
      if (!res.ok) {
        const errBody = await res.json().catch(() => null)
        const detail = errBody?.error ?? `Gateway error (HTTP ${res.status})`
        throw new Error(detail)
      }
      const data = await res.json()
      setChatThreadId(data.thread_id)
      setChatRunId(data.run_id)
      startChatPolling(data.thread_id, data.run_id)
    } catch (err) {
      setChatStreaming(false)
      const detail = err instanceof Error ? err.message : 'Unknown error'
      setChatMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Error: could not reach the AI agent. ${detail}` },
      ])
    }
  }

  async function openChat() {
    setChatOpen(true)
    if (chatMessages.length === 0) {
      await sendChatMessage(
        'Summarize what you know about this VM and suggest the next investigation steps.'
      )
    }
  }

  // Reset chat when a different VM is opened
  useEffect(() => {
    setChatOpen(false)
    setChatMessages([])
    setChatInput('')
    setChatThreadId(null)
    setChatRunId(null)
  }, [resourceId])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (chatPollRef.current) clearInterval(chatPollRef.current)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchVM()
    fetchEvidence()
    fetchMetrics()
    fetchDiagSettings()
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
              <div>
                <div className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
                  {vm.name || resourceName || 'VM Detail'}
                </div>
                <div className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                  {vm.subscription_id}
                </div>
              </div>
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
                <div className="flex items-center gap-1">
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
                  {/* Metric selector */}
                  <div className="relative ml-1">
                    <button
                      onClick={() => setMetricSelectorOpen(v => !v)}
                      className="text-[10px] px-1.5 py-0.5 rounded cursor-pointer font-bold"
                      style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
                      title="Add / remove metrics"
                    >
                      ＋
                    </button>
                    {metricSelectorOpen && (
                      <div
                        className="absolute right-0 top-6 z-50 rounded-lg shadow-xl overflow-y-auto"
                        style={{
                          width: '220px',
                          maxHeight: '320px',
                          background: 'var(--bg-surface)',
                          border: '1px solid var(--border)',
                        }}
                      >
                        <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>
                          Select metrics
                        </div>
                        {(['CPU', 'Memory', 'Disk', 'Network', 'Availability'] as const).map(group => (
                          <div key={group}>
                            <div className="px-3 pt-2 pb-1 text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                              {group}
                            </div>
                            {METRIC_CATALOG.filter(m => m.group === group).map(m => (
                              <label
                                key={m.name}
                                className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:opacity-80"
                                style={{ color: 'var(--text-secondary)' }}
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedMetrics.includes(m.name)}
                                  onChange={e => {
                                    setSelectedMetrics(prev =>
                                      e.target.checked
                                        ? [...prev, m.name]
                                        : prev.filter(n => n !== m.name)
                                    )
                                  }}
                                  className="accent-[var(--accent-blue)]"
                                />
                                <span className="text-[11px]">{m.label}</span>
                              </label>
                            ))}
                          </div>
                        ))}
                        <div className="px-3 py-2" style={{ borderTop: '1px solid var(--border)' }}>
                          <button
                            onClick={() => setMetricSelectorOpen(false)}
                            className="w-full text-[11px] py-1 rounded cursor-pointer"
                            style={{ background: 'var(--accent-blue)', color: 'white' }}
                          >
                            Done
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {metricsLoading ? (
                <div className="space-y-2">
                  {[...Array(selectedMetrics.length || 4)].map((_, i) => (
                    <div key={i} className="h-10 rounded animate-pulse" style={{ background: 'var(--bg-subtle)' }} />
                  ))}
                </div>
              ) : metrics.length === 0 || metrics.every(m => m.timeseries.length === 0) ? (
                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {vm.power_state === 'deallocated'
                    ? 'No metrics — VM is deallocated. Start the VM to collect data.'
                    : 'No metrics available'}
                </div>
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

              {/* Diagnostic settings status — shown below metrics regardless of data */}
              {diagConfigured === false && (
                <div
                  className="mt-3 rounded-md p-2 text-xs flex items-start justify-between gap-2"
                  style={{ background: `color-mix(in srgb, var(--accent-blue) 8%, transparent)`, border: '1px solid color-mix(in srgb, var(--accent-blue) 20%, transparent)' }}
                >
                  <span style={{ color: 'var(--text-secondary)' }}>
                    Diagnostic settings not configured. Enable to send all logs &amp; metrics to the platform workspace.
                  </span>
                  <button
                    onClick={enableDiagSettings}
                    disabled={diagEnabling}
                    className="flex-shrink-0 px-2 py-1 rounded text-[11px] font-medium cursor-pointer disabled:opacity-50"
                    style={{ background: 'var(--accent-blue)', color: 'white' }}
                  >
                    {diagEnabling ? 'Enabling…' : 'Enable'}
                  </button>
                </div>
              )}
              {diagConfigured === true && (
                <div className="mt-2 text-[11px]" style={{ color: 'var(--accent-green)' }}>
                  ✓ Diagnostic settings configured
                </div>
              )}
              {diagError && (
                <div className="mt-1 text-xs" style={{ color: 'var(--accent-red)' }}>{diagError}</div>
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

            {/* AI Investigation */}
            <div className="px-4 py-3">
              <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                AI Investigation
              </div>

              {!chatOpen ? (
                <button
                  className="w-full text-sm py-2 px-3 rounded-md cursor-pointer text-center transition-colors"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                    color: 'var(--accent-blue)',
                    border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
                  }}
                  onClick={openChat}
                >
                  Investigate with AI
                </button>
              ) : (
                <div className="flex flex-col gap-2">
                  {/* Message history */}
                  <div
                    className="overflow-y-auto rounded-md p-2 space-y-2"
                    style={{
                      maxHeight: '320px',
                      background: 'var(--bg-canvas)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    {chatMessages.length === 0 && chatStreaming && (
                      <div className="space-y-1 animate-pulse p-2">
                        {[...Array(3)].map((_, i) => (
                          <div
                            key={i}
                            className="h-3 rounded"
                            style={{ background: 'var(--bg-subtle)', width: i === 2 ? '60%' : '100%' }}
                          />
                        ))}
                      </div>
                    )}
                    {chatMessages.map((msg, i) => (
                      <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        {msg.approval_id ? (
                          <div
                            className="text-xs p-2 rounded-md max-w-[85%]"
                            style={{
                              background: 'color-mix(in srgb, var(--accent-orange) 10%, transparent)',
                              border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)',
                              color: 'var(--text-primary)',
                            }}
                          >
                            ⚠️ Remediation proposal — open full chat to approve
                          </div>
                        ) : (
                          <div
                            className="text-xs p-2 rounded-md max-w-[85%] whitespace-pre-wrap"
                            style={{
                              background: msg.role === 'user'
                                ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
                                : 'var(--bg-subtle)',
                              color: 'var(--text-primary)',
                            }}
                          >
                            {msg.content}
                          </div>
                        )}
                      </div>
                    ))}
                    {chatStreaming && chatMessages.length > 0 && (
                      <div className="flex justify-start">
                        <div className="text-xs px-2 py-1 rounded-md animate-pulse" style={{ color: 'var(--text-muted)' }}>
                          Thinking…
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Input */}
                  <div className="flex gap-1">
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          sendChatMessage(chatInput)
                        }
                      }}
                      placeholder="Ask about this VM…"
                      disabled={chatStreaming}
                      className="flex-1 text-xs px-2 py-1.5 rounded-md outline-none"
                      style={{
                        background: 'var(--bg-canvas)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-primary)',
                      }}
                    />
                    <button
                      onClick={() => sendChatMessage(chatInput)}
                      disabled={chatStreaming || !chatInput.trim()}
                      className="text-xs px-2 py-1.5 rounded-md cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{ background: 'var(--accent-blue)', color: 'white' }}
                    >
                      Send
                    </button>
                  </div>
                </div>
              )}
            </div>

          </div>
        ) : null}
      </div>
    </div>
  )
}
