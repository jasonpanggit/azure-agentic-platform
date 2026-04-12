'use client'

import { useState, useEffect, useCallback, useRef, MouseEvent as ReactMouseEvent } from 'react'
import { X, RefreshCw, Activity, Info } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type {
  AKSCluster,
  AKSNodePool,
  AKSWorkloadSummary,
  ActiveIncident,
  MetricSeries,
  ChatMessage,
} from '@/types/azure-resources'

// ── Constants ────────────────────────────────────────────────────────────────

const PANEL_MIN_WIDTH = 380
const PANEL_MAX_WIDTH = 1200
const PANEL_DEFAULT_WIDTH = 560

type DetailTab = 'overview' | 'nodepools' | 'workloads' | 'metrics' | 'chat'

interface AKSDetailPanelProps {
  resourceId: string
  resourceName: string
  onClose: () => void
}

// Detail response shape (extends AKSCluster with nested data)
interface AKSDetail extends AKSCluster {
  node_pools: AKSNodePool[]
  workload_summary: AKSWorkloadSummary | null
  active_incidents: ActiveIncident[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function encodeResourceId(resourceId: string): string {
  return btoa(resourceId).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

function SeverityBadge({ severity }: { severity: string }) {
  const config: Record<string, { label: string; color: string }> = {
    sev0: { label: 'Sev 0', color: 'var(--accent-red)' },
    sev1: { label: 'Sev 1', color: 'var(--accent-red)' },
    sev2: { label: 'Sev 2', color: 'var(--accent-orange)' },
    sev3: { label: 'Sev 3', color: 'var(--accent-yellow)' },
    sev4: { label: 'Sev 4', color: 'var(--text-muted)' },
  }
  const c = config[severity.toLowerCase()] ?? { label: severity, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold"
      style={{
        background: `color-mix(in srgb, ${c.color} 15%, transparent)`,
        color: c.color,
      }}
    >
      {c.label}
    </span>
  )
}

function NodePoolModeBadge({ mode }: { mode: 'System' | 'User' }) {
  const color = mode === 'System' ? 'var(--accent-blue)' : 'var(--text-muted)'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {mode}
    </span>
  )
}

function NodeReadyBadge({ ready, total }: { ready: number; total: number }) {
  const notReady = total - ready
  const color = notReady === 0 ? 'var(--accent-green)' : notReady / total > 0.5 ? 'var(--accent-red)' : 'var(--accent-yellow)'
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {ready}/{total}
    </span>
  )
}

// ── Sparkline chart ───────────────────────────────────────────────────────────

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

// ── AKS metrics catalog ───────────────────────────────────────────────────────

interface MetricOption {
  name: string
  label: string
  group: string
}

const AKS_METRIC_CATALOG: MetricOption[] = [
  // Node
  { name: 'node_cpu_usage_percentage',          label: 'Node CPU %',         group: 'Node' },
  { name: 'node_memory_working_set_percentage', label: 'Node Memory %',      group: 'Node' },
  { name: 'node_memory_rss_percentage',         label: 'Node RSS %',         group: 'Node' },
  { name: 'node_disk_usage_bytes',              label: 'Node Disk',          group: 'Node' },
  { name: 'node_network_in_bytes',              label: 'Node Net In',        group: 'Node' },
  { name: 'node_network_out_bytes',             label: 'Node Net Out',       group: 'Node' },
  // Workloads
  { name: 'kube_pod_status_ready',              label: 'Pods Ready',         group: 'Workloads' },
  { name: 'kube_node_status_condition',         label: 'Node Condition',     group: 'Workloads' },
  // API Server
  { name: 'apiserver_request_total',            label: 'API Requests',       group: 'API Server' },
  { name: 'cluster_autoscaler_unschedulable_pods_count', label: 'Unschedulable Pods', group: 'API Server' },
]

const AKS_DEFAULT_SELECTED = [
  'node_cpu_usage_percentage',
  'node_memory_working_set_percentage',
  'node_network_in_bytes',
  'node_network_out_bytes',
  'kube_pod_status_ready',
  'apiserver_request_total',
]

// ── Main Component ────────────────────────────────────────────────────────────

export function AKSDetailPanel({ resourceId, resourceName, onClose }: AKSDetailPanelProps) {
  const { instance, accounts } = useMsal()
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [detail, setDetail] = useState<AKSDetail | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [metricsTimespan, setMetricsTimespan] = useState<'PT1H' | 'PT6H' | 'PT24H' | 'P7D'>('PT24H')
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(AKS_DEFAULT_SELECTED)
  const [metricSelectorOpen, setMetricSelectorOpen] = useState(false)
  const metricsLoadedForTimeRange = useRef<string | null>(null)
  const [enablingContainerInsights, setEnablingContainerInsights] = useState(false)

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatThreadId, setChatThreadId] = useState<string | null>(null)
  const chatAutoFired = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Resize state
  const [panelWidth, setPanelWidth] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('aksDetailPanelWidth')
      if (stored) return Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, parseInt(stored, 10)))
    }
    return PANEL_DEFAULT_WIDTH
  })
  const dragging = useRef(false)
  const dragStartX = useRef(0)
  const dragStartWidth = useRef(PANEL_DEFAULT_WIDTH)

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

  async function fetchDetail() {
    if (!resourceId) return
    setLoadingDetail(true)
    setError(null)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks/${encoded}`, { headers })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const data = await res.json()
      if ('error' in data && typeof data.error === 'string') {
        setError(data.error)
        return
      }
      if (data.fetch_error) {
        setError(`Failed to load cluster details: ${data.fetch_error}`)
      }
      setDetail(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(`Failed to load cluster details: ${msg}`)
    } finally {
      setLoadingDetail(false)
    }
  }

  async function fetchMetrics(timespan: string) {
    if (!resourceId) return
    setLoadingMetrics(true)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(
        `/api/proxy/aks/${encoded}/metrics?timespan=${timespan}&metrics=${encodeURIComponent(selectedMetrics.join(','))}`,
        { headers }
      )
      if (res.ok) {
        const data = await res.json()
        setMetrics(data.metrics ?? [])
      }
    } catch {
      // Non-fatal
    } finally {
      setLoadingMetrics(false)
    }
  }

  async function handleEnableContainerInsights() {
    if (!detail) return
    setEnablingContainerInsights(true)
    try {
      const encoded = encodeResourceId(detail.id)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks/${encoded}/monitoring`, { method: 'POST', headers })
      if (res.ok) {
        const data = await res.json()
        if (data.success) {
          // Refresh detail so the banner reflects updated addon status
          await fetchDetail()
        }
      }
    } catch {
      // Non-fatal — user can retry
    } finally {
      setEnablingContainerInsights(false)
    }
  }

  async function sendChatMessage(message: string) {
    if (!message.trim() || chatLoading) return
    setChatLoading(true)
    setChatMessages(prev => [...prev, { role: 'user', content: message }])
    setChatInput('')
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks/${encoded}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message, thread_id: chatThreadId }),
      })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const { thread_id, run_id } = await res.json()
      if (thread_id) setChatThreadId(thread_id)
      await pollChatResult(thread_id, run_id, token)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setChatMessages(prev => [...prev, { role: 'assistant', content: `Error: ${msg}` }])
    } finally {
      setChatLoading(false)
    }
  }

  async function pollChatResult(threadId: string, runId: string, token: string | null) {
    const TERMINAL = ['completed', 'failed', 'cancelled', 'expired']
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/chat/result?thread_id=${threadId}&run_id=${runId}`, { headers })
      if (!res.ok) continue
      const data = await res.json()
      if (TERMINAL.includes(data.status)) {
        if (data.response) setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }])
        return
      }
    }
  }

  useEffect(() => {
    setChatMessages([])
    setChatThreadId(null)
    chatAutoFired.current = false
    setActiveTab('overview')
    fetchDetail()
  }, [resourceId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === 'chat' && !chatAutoFired.current && !chatLoading) {
      chatAutoFired.current = true
      sendChatMessage("Summarize this cluster's health and suggest investigation steps.")
    }
    if (activeTab === 'metrics') fetchMetrics(metricsTimespan)
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === 'metrics') fetchMetrics(metricsTimespan)
  }, [metricsTimespan, selectedMetrics]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  function onDragStart(e: ReactMouseEvent) {
    dragging.current = true
    dragStartX.current = e.clientX
    dragStartWidth.current = panelWidth
    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragEnd)
    e.preventDefault()
  }
  function onDragMove(e: MouseEvent) {
    if (!dragging.current) return
    const delta = dragStartX.current - e.clientX
    const newWidth = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, dragStartWidth.current + delta))
    setPanelWidth(newWidth)
  }
  function onDragEnd() {
    dragging.current = false
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
    localStorage.setItem('aksDetailPanelWidth', String(panelWidth))
  }

  const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'nodepools', label: 'Node Pools' },
    { id: 'workloads', label: 'Workloads' },
    { id: 'metrics', label: 'Metrics' },
    { id: 'chat', label: 'AI Chat' },
  ]

  return (
    <div
      className="fixed top-0 right-0 h-full z-40 flex flex-col overflow-hidden"
      style={{
        width: `${panelWidth}px`,
        background: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border)',
        boxShadow: '-4px 0 24px rgba(0,0,0,0.12)',
      }}
    >
      {/* Drag resize handle */}
      <div
        className="absolute top-0 left-0 h-full w-1.5 cursor-col-resize z-50 transition-colors"
        style={{ backgroundColor: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)' }}
        onMouseDown={onDragStart}
        title="Drag to resize"
      />

      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
            {resourceName}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchDetail}
            disabled={loadingDetail}
            className="p-1.5 rounded cursor-pointer"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loadingDetail ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded cursor-pointer"
            style={{ color: 'var(--text-secondary)' }}
            title="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Detail tabs */}
      <div
        className="flex items-end flex-shrink-0 px-4"
        style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        {DETAIL_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="px-3 py-2 text-[12px] font-medium transition-colors cursor-pointer"
            style={{
              color: activeTab === tab.id ? 'var(--text-primary)' : 'var(--text-secondary)',
              borderBottom: activeTab === tab.id ? '2px solid var(--accent-blue)' : '2px solid transparent',
              marginBottom: '-1px',
              background: 'transparent',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="p-4 text-sm" style={{ color: 'var(--accent-red)' }}>{error}</div>
        )}

        {/* Overview tab */}
        {activeTab === 'overview' && (
          <div className="p-4 space-y-4">
            {loadingDetail ? (
              <div className="space-y-3 animate-pulse">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-16 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : detail && !(detail as AKSDetail & { fetch_error?: string }).fetch_error ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Nodes Ready', value: `${detail.ready_nodes}/${detail.total_nodes}`, color: detail.ready_nodes === detail.total_nodes && detail.total_nodes > 0 ? 'var(--accent-green)' : 'var(--accent-yellow)' },
                    { label: 'Node Pools', value: `${detail.node_pools_ready}/${detail.node_pool_count}`, color: detail.node_pools_ready === detail.node_pool_count && detail.node_pool_count > 0 ? 'var(--accent-green)' : 'var(--accent-yellow)' },
                    { label: 'K8s Version', value: detail.kubernetes_version || '—', color: 'var(--text-primary)' },
                    { label: 'System Pods', value: detail.system_pod_health, color: detail.system_pod_health === 'healthy' ? 'var(--accent-green)' : detail.system_pod_health === 'degraded' ? 'var(--accent-yellow)' : 'var(--text-muted)' },
                  ].map(card => (
                    <div
                      key={card.label}
                      className="p-3 rounded-lg"
                      style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                    >
                      <p className="text-[11px] uppercase tracking-wide mb-1" style={{ color: 'var(--text-muted)' }}>
                        {card.label}
                      </p>
                      <p className="text-lg font-semibold" style={{ color: card.color }}>
                        {card.value}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Metadata */}
                <div
                  className="rounded-lg p-3"
                  style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                >
                  <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                    Cluster Configuration
                  </p>
                  {[
                    ['Location', detail.location || '—'],
                    ['FQDN', detail.fqdn ?? '—'],
                    ['Network Plugin', detail.network_plugin || '—'],
                    ['RBAC Enabled', detail.rbac_enabled ? 'Yes' : 'No'],
                    ['Latest K8s Available', detail.latest_available_version ?? 'Up to date'],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1 text-xs" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
                    </div>
                  ))}
                </div>

                {/* Active incidents */}
                {detail.active_incidents?.length > 0 && (
                  <div
                    className="rounded-lg p-3"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                      Active Incidents
                    </p>
                    {detail.active_incidents.map((inc: ActiveIncident) => (
                      <div key={inc.incident_id} className="flex items-center justify-between py-1.5 text-xs" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <span className="font-mono" style={{ color: 'var(--text-primary)' }}>
                          {inc.title ?? inc.incident_id}
                        </span>
                        <SeverityBadge severity={inc.severity} />
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : null}
          </div>
        )}

        {/* Node Pools tab */}
        {activeTab === 'nodepools' && (
          <div className="p-4">
            {loadingDetail ? (
              <div className="animate-pulse space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-12 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : !detail?.node_pools?.length ? (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                No node pool data available
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Pool', 'VM Size', 'Nodes', 'Mode', 'OS', 'Scale Range'].map(col => (
                      <th key={col} className="text-left px-2 py-2 text-[11px] uppercase tracking-wide font-semibold" style={{ color: 'var(--text-muted)' }}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.node_pools.map((pool: AKSNodePool) => (
                    <tr
                      key={pool.name}
                      style={{
                        borderBottom: '1px solid var(--border-subtle)',
                        background: pool.ready_node_count < pool.node_count
                          ? 'color-mix(in srgb, var(--accent-yellow) 5%, transparent)'
                          : 'transparent',
                      }}
                    >
                      <td className="px-2 py-2 font-mono font-medium" style={{ color: 'var(--text-primary)' }}>
                        {pool.name}
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {pool.vm_size}
                      </td>
                      <td className="px-2 py-2">
                        <NodeReadyBadge ready={pool.ready_node_count} total={pool.node_count} />
                      </td>
                      <td className="px-2 py-2">
                        <NodePoolModeBadge mode={pool.mode} />
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {pool.os_type}
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {pool.min_count !== null && pool.max_count !== null
                          ? `${pool.min_count}–${pool.max_count}`
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Workloads tab */}
        {activeTab === 'workloads' && (
          <div className="p-4 space-y-4">
            {loadingDetail ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-16 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : detail?.workload_summary ? (
              <>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Running Pods', value: String(detail.workload_summary.running_pods), color: 'var(--accent-green)' },
                    { label: 'CrashLoopBackOff', value: String(detail.workload_summary.crash_loop_pods), color: detail.workload_summary.crash_loop_pods > 0 ? 'var(--accent-red)' : 'var(--text-muted)' },
                    { label: 'Pending Pods', value: String(detail.workload_summary.pending_pods), color: detail.workload_summary.pending_pods > 0 ? 'var(--accent-yellow)' : 'var(--text-muted)' },
                    { label: 'Namespaces', value: String(detail.workload_summary.namespace_count), color: 'var(--text-primary)' },
                  ].map(card => (
                    <div
                      key={card.label}
                      className="p-3 rounded-lg"
                      style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                    >
                      <p className="text-[11px] uppercase tracking-wide mb-1" style={{ color: 'var(--text-muted)' }}>
                        {card.label}
                      </p>
                      <p className="text-lg font-semibold" style={{ color: card.color }}>
                        {card.value}
                      </p>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-center py-2" style={{ color: 'var(--text-muted)' }}>
                  Use AI Chat for detailed workload investigation.
                </p>
              </>
            ) : (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                No workload data available
              </p>
            )}
          </div>
        )}

        {/* Metrics tab */}
        {activeTab === 'metrics' && (
          <div className="p-4 space-y-3">
            {/* Container Insights status banner */}
            {detail && !detail.container_insights_enabled && (
              <div
                className="flex items-start gap-3 px-3 py-2.5 rounded-lg text-xs"
                style={{
                  background: 'color-mix(in srgb, var(--accent-yellow) 12%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
                }}
              >
                <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" style={{ color: 'var(--accent-yellow)' }} />
                <span style={{ color: 'var(--text-secondary)' }}>
                  Showing platform metrics. <strong style={{ color: 'var(--text-primary)' }}>Container Insights</strong> not
                  enabled — logs and richer telemetry unavailable.
                </span>
                <button
                  onClick={handleEnableContainerInsights}
                  disabled={enablingContainerInsights}
                  className="ml-auto shrink-0 px-2.5 py-1 rounded text-[11px] font-medium transition-opacity disabled:opacity-60 cursor-pointer"
                  style={{ background: 'var(--accent-blue)', color: '#fff' }}
                >
                  {enablingContainerInsights ? 'Enabling…' : 'Enable'}
                </button>
              </div>
            )}

            {/* Time range selector */}
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>Azure Monitor Metrics</p>
              <div className="flex items-center gap-1">
                {(['PT1H', 'PT6H', 'PT24H', 'P7D'] as const).map(r => (
                  <button
                    key={r}
                    onClick={() => setMetricsTimespan(r)}
                    className="text-[10px] px-1.5 py-0.5 rounded cursor-pointer"
                    style={{
                      background: metricsTimespan === r ? 'var(--accent-blue)' : 'var(--bg-subtle)',
                      color: metricsTimespan === r ? 'white' : 'var(--text-secondary)',
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
                        maxHeight: '420px',
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border)',
                      }}
                    >
                      <div className="px-3 py-2 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
                        <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>Select metrics</span>
                        <div className="flex gap-2">
                          <button
                            onClick={() => setSelectedMetrics(AKS_METRIC_CATALOG.map(m => m.name))}
                            className="text-[10px] cursor-pointer hover:opacity-70"
                            style={{ color: 'var(--accent-blue)' }}
                          >All</button>
                          <button
                            onClick={() => setSelectedMetrics(AKS_DEFAULT_SELECTED)}
                            className="text-[10px] cursor-pointer hover:opacity-70"
                            style={{ color: 'var(--text-muted)' }}
                          >Reset</button>
                        </div>
                      </div>
                      {(['Node', 'Workloads', 'API Server'] as const).map(group => (
                        <div key={group}>
                          <div className="px-3 pt-2 pb-1 text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                            {group}
                          </div>
                          {AKS_METRIC_CATALOG.filter(m => m.group === group).map(m => (
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

            {loadingMetrics ? (
              <div className="space-y-2">
                {[...Array(selectedMetrics.length || 4)].map((_, i) => (
                  <div key={i} className="h-10 rounded animate-pulse" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : metrics.length === 0 || metrics.every(m =>
              m.timeseries.length === 0 || m.timeseries.every(p => p.average == null)
            ) ? (
              <div className="py-8 text-center space-y-3">
                <Activity className="h-8 w-8 mx-auto" style={{ color: 'var(--text-muted)' }} />
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                  No metrics available
                </p>
                {detail && !detail.container_insights_enabled ? (
                  <>
                    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                      Enable Container Insights to collect node-level metrics.
                    </p>
                    <button
                      onClick={handleEnableContainerInsights}
                      disabled={enablingContainerInsights}
                      className="mx-auto flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-opacity disabled:opacity-60 cursor-pointer"
                      style={{ background: 'var(--accent-blue)', color: '#fff' }}
                    >
                      {enablingContainerInsights ? 'Enabling…' : 'Enable Container Insights'}
                    </button>
                  </>
                ) : (
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    Platform metrics may take a few minutes to appear for a new cluster.
                  </p>
                )}
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
                          {AKS_METRIC_CATALOG.find(c => c.name === m.name)?.label ?? m.name ?? '—'}
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
        )}

        {/* Chat tab */}
        {activeTab === 'chat' && (
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className="max-w-[85%] px-3 py-2 rounded-lg text-sm"
                    style={{
                      background: msg.role === 'user'
                        ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
                        : 'var(--bg-canvas)',
                      color: 'var(--text-primary)',
                      border: msg.role === 'assistant' ? '1px solid var(--border)' : 'none',
                    }}
                  >
                    <p className="whitespace-pre-wrap text-xs leading-relaxed">{msg.content}</p>
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div
                    className="px-3 py-2 rounded-lg"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <div className="flex gap-1 items-center">
                      <div className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '0ms' }} />
                      <div className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '150ms' }} />
                      <div className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
            <div
              className="flex gap-2 p-3 flex-shrink-0"
              style={{ borderTop: '1px solid var(--border)' }}
            >
              <input
                type="text"
                placeholder="Ask about this cluster…"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(chatInput) } }}
                disabled={chatLoading}
                className="flex-1 text-xs px-3 py-2 rounded-md outline-none"
                style={{
                  background: 'var(--bg-canvas)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                }}
              />
              <button
                onClick={() => sendChatMessage(chatInput)}
                disabled={chatLoading || !chatInput.trim()}
                className="px-3 py-2 rounded-md text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                style={{ background: 'var(--accent-blue)', color: '#fff' }}
              >
                Send
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
