'use client'

import { useState, useEffect, useCallback, useRef, MouseEvent as ReactMouseEvent } from 'react'
import { X, RefreshCw, Activity } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { VMSSDetail, VMSSInstance, ActiveIncident, MetricSeries, ChatMessage } from '@/types/azure-resources'

// ── Constants ────────────────────────────────────────────────────────────────

const PANEL_MIN_WIDTH = 380
const PANEL_MAX_WIDTH = 1200
const PANEL_DEFAULT_WIDTH = 520

type DetailTab = 'overview' | 'instances' | 'metrics' | 'scaling' | 'chat'

interface VMSSDetailPanelProps {
  resourceId: string
  resourceName: string
  onClose: () => void
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

function HealthStateBadge({ state }: { state: string }) {
  const config: Record<string, { label: string; color: string }> = {
    available: { label: 'Healthy', color: 'var(--accent-green)' },
    degraded: { label: 'Degraded', color: 'var(--accent-orange)' },
    unavailable: { label: 'Unavailable', color: 'var(--accent-red)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
    running: { label: 'Running', color: 'var(--accent-green)' },
    stopped: { label: 'Stopped', color: 'var(--accent-yellow)' },
  }
  const c = config[state.toLowerCase()] ?? { label: state, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${c.color} 15%, transparent)`,
        color: c.color,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.color }} />
      {c.label}
    </span>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function VMSSDetailPanel({ resourceId, resourceName, onClose }: VMSSDetailPanelProps) {
  const { instance, accounts } = useMsal()
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [detail, setDetail] = useState<VMSSDetail | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [metricsTimespan, setMetricsTimespan] = useState('PT24H')
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [instanceSearch, setInstanceSearch] = useState('')

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
      const stored = localStorage.getItem('vmssDetailPanelWidth')
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

  // Fetch detail data
  async function fetchDetail() {
    if (!resourceId) return
    setLoadingDetail(true)
    setError(null)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vmss/${encoded}`, { headers })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const data = await res.json()
      setDetail(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(`Failed to load scale set details: ${msg}`)
    } finally {
      setLoadingDetail(false)
    }
  }

  // Fetch metrics
  async function fetchMetrics(timespan: string) {
    if (!resourceId) return
    setLoadingMetrics(true)
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const url = `/api/proxy/vmss/${encoded}/metrics?timespan=${timespan}`
      const res = await fetch(url, { headers })
      if (res.ok) {
        const data = await res.json()
        setMetrics(data.metrics ?? [])
      }
    } catch {
      // Non-fatal — metrics chart shows empty state
    } finally {
      setLoadingMetrics(false)
    }
  }

  // Chat: send message
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
      const res = await fetch(`/api/proxy/vmss/${encoded}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message, thread_id: chatThreadId }),
      })
      if (!res.ok) throw new Error(`Status ${res.status}`)
      const { thread_id, run_id } = await res.json()
      if (thread_id) setChatThreadId(thread_id)
      // Poll for result
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
        if (data.response) {
          setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }])
        }
        return
      }
    }
  }

  // Reset when resource changes
  useEffect(() => {
    setChatMessages([])
    setChatThreadId(null)
    chatAutoFired.current = false
    setActiveTab('overview')
    fetchDetail()
  }, [resourceId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-fire chat on first open of Chat tab
  useEffect(() => {
    if (activeTab === 'chat' && !chatAutoFired.current && !chatLoading) {
      chatAutoFired.current = true
      sendChatMessage("Summarize this scale set's health and suggest investigation steps.")
    }
    if (activeTab === 'metrics') {
      fetchMetrics(metricsTimespan)
    }
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === 'metrics') fetchMetrics(metricsTimespan)
  }, [metricsTimespan]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll chat to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // Drag resize handlers
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
    localStorage.setItem('vmssDetailPanelWidth', String(panelWidth))
  }

  const DETAIL_TABS: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'instances', label: 'Instances' },
    { id: 'metrics', label: 'Metrics' },
    { id: 'scaling', label: 'Scaling' },
    { id: 'chat', label: 'AI Chat' },
  ]

  const filteredInstances = (detail?.instances ?? []).filter(inst =>
    !instanceSearch || inst.instance_id.includes(instanceSearch) || inst.name.toLowerCase().includes(instanceSearch.toLowerCase())
  )

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
            ) : detail ? (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: 'Healthy Instances', value: String(detail.healthy_instance_count), color: 'var(--accent-green)' },
                    { label: 'Total Instances', value: String(detail.instance_count), color: 'var(--text-primary)' },
                    { label: 'Active Alerts', value: String(detail.active_alert_count), color: detail.active_alert_count > 0 ? 'var(--accent-red)' : 'var(--text-muted)' },
                    { label: 'Autoscale', value: detail.autoscale_enabled ? 'Enabled' : 'Disabled', color: detail.autoscale_enabled ? 'var(--accent-green)' : 'var(--text-muted)' },
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
                    Configuration
                  </p>
                  {[
                    ['SKU', detail.sku || '—'],
                    ['Location', detail.location],
                    ['OS Image', detail.os_image_version || '—'],
                    ['Upgrade Policy', detail.upgrade_policy || '—'],
                    ['Scale Range', `${detail.min_count} – ${detail.max_count}`],
                    ['Health State', detail.health_state],
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

        {/* Instances tab */}
        {activeTab === 'instances' && (
          <div className="p-4">
            <div className="mb-3">
              <input
                type="text"
                placeholder="Search instances…"
                value={instanceSearch}
                onChange={(e) => setInstanceSearch(e.target.value)}
                className="text-xs px-3 py-1.5 rounded-md outline-none w-full"
                style={{
                  background: 'var(--bg-canvas)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>
            {loadingDetail ? (
              <div className="animate-pulse space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-10 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : filteredInstances.length === 0 ? (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                No instance data available
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Instance', 'Power State', 'Health', 'Provisioning'].map(col => (
                      <th key={col} className="text-left px-2 py-2 text-[11px] uppercase tracking-wide font-semibold" style={{ color: 'var(--text-muted)' }}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredInstances.map((inst: VMSSInstance) => (
                    <tr
                      key={inst.instance_id}
                      style={{ borderBottom: '1px solid var(--border-subtle)' }}
                    >
                      <td className="px-2 py-2 font-mono" style={{ color: 'var(--text-primary)' }}>
                        {inst.name || inst.instance_id}
                      </td>
                      <td className="px-2 py-2">
                        <HealthStateBadge state={inst.power_state} />
                      </td>
                      <td className="px-2 py-2">
                        <HealthStateBadge state={inst.health_state} />
                      </td>
                      <td className="px-2 py-2" style={{ color: 'var(--text-secondary)' }}>
                        {inst.provisioning_state}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Metrics tab */}
        {activeTab === 'metrics' && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>Azure Monitor Metrics</p>
              <select
                value={metricsTimespan}
                onChange={(e) => setMetricsTimespan(e.target.value)}
                className="text-xs px-2 py-1 rounded outline-none"
                style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
              >
                <option value="PT1H">Last 1h</option>
                <option value="PT6H">Last 6h</option>
                <option value="PT24H">Last 24h</option>
                <option value="P7D">Last 7d</option>
              </select>
            </div>
            {loadingMetrics ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-24 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : metrics.length === 0 ? (
              <div className="py-8 text-center">
                <Activity className="h-8 w-8 mx-auto mb-2" style={{ color: 'var(--text-muted)' }} />
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                  No metrics available
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {metrics.map((m, i) => (
                  <div
                    key={i}
                    className="p-3 rounded-lg"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                      {m.name ?? 'Metric'} {m.unit ? `(${m.unit})` : ''}
                    </p>
                    <p className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                      {m.timeseries?.length ?? 0} data points
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Scaling tab */}
        {activeTab === 'scaling' && (
          <div className="p-4">
            {loadingDetail ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-16 rounded" style={{ background: 'var(--bg-subtle)' }} />
                ))}
              </div>
            ) : detail ? (
              <div className="space-y-4">
                <div
                  className="p-3 rounded-lg"
                  style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                >
                  <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                    Autoscale Configuration
                  </p>
                  {[
                    ['Autoscale Enabled', detail.autoscale_enabled ? 'Yes' : 'No'],
                    ['Min Instances', String(detail.min_count)],
                    ['Max Instances', String(detail.max_count)],
                    ['Current Instances', String(detail.instance_count)],
                    ['Upgrade Policy', detail.upgrade_policy || '—'],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1 text-xs" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                      <span style={{ color: 'var(--text-primary)' }}>{v}</span>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>
                  Use AI Chat to propose scale adjustments via the HITL approval workflow.
                </p>
              </div>
            ) : (
              <p className="text-sm text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                Loading scale set configuration…
              </p>
            )}
          </div>
        )}

        {/* Chat tab */}
        {activeTab === 'chat' && (
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
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
                placeholder="Ask about this scale set…"
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
                style={{
                  background: 'var(--accent-blue)',
                  color: '#fff',
                }}
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
