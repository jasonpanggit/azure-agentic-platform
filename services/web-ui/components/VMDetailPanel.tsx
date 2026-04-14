'use client'

import { useState, useEffect, useCallback, useRef, useMemo, MouseEvent as ReactMouseEvent } from 'react'
import { X, RefreshCw, AlertTriangle, CheckCircle, XCircle, HelpCircle, Activity, ShieldAlert, Package } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import { CveBadges } from './CveDetailDialog'
import type {
  VMDetail,
  ActiveIncident,
  Evidence,
  MetricSeries,
  ChatMessage,
} from '@/types/azure-resources'

// ── Constants ────────────────────────────────────────────────────────────────

const PANEL_MIN_WIDTH = 380
const PANEL_MAX_WIDTH = 1200
const PANEL_DEFAULT_WIDTH = 480

type DetailTab = 'overview' | 'metrics' | 'evidence' | 'patches' | 'chat'

// ── Props ─────────────────────────────────────────────────────────────────────

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

// Arc VMs use Log Analytics Perf table — fewer metrics available, different names
const ARC_METRIC_CATALOG: MetricOption[] = [
  { name: 'Percentage CPU',         label: 'CPU %',       group: 'CPU' },
  { name: 'Available Memory Bytes', label: 'Free Memory', group: 'Memory' },
  { name: 'Disk Read Bytes',        label: 'Disk Read',   group: 'Disk' },
  { name: 'Disk Write Bytes',       label: 'Disk Write',  group: 'Disk' },
  { name: 'Network In Total',       label: 'Net In',      group: 'Network' },
  { name: 'Network Out Total',      label: 'Net Out',     group: 'Network' },
]

const ARC_DEFAULT_METRICS = [
  'Percentage CPU',
  'Available Memory Bytes',
  'Disk Read Bytes',
  'Disk Write Bytes',
  'Network In Total',
  'Network Out Total',
]

const DETAIL_TABS: { id: DetailTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'metrics',  label: 'Metrics' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'patches',  label: 'Patches' },
  { id: 'chat',     label: 'AI Chat' },
]

// ── Patch types & helpers ─────────────────────────────────────────────────────

interface PendingPatch {
  readonly patchName: string
  readonly classifications: readonly string[]
  readonly rebootRequired: boolean
  readonly kbid: string
  readonly version: string
  readonly publishedDateTime: string | null
  readonly cves: readonly string[]
}

interface InstalledPatch {
  readonly SoftwareName: string
  readonly SoftwareType: string
  readonly CurrentVersion: string
  readonly Publisher: string
  readonly Category: string
  readonly InstalledDate: string
  readonly cves: readonly string[]
}

type PatchSubTab = 'pending' | 'installed'
type DaysOption = '30' | '90' | '180' | '365'

const DAYS_OPTIONS: readonly { readonly value: DaysOption; readonly label: string }[] = [
  { value: '30', label: '30d' },
  { value: '90', label: '90d' },
  { value: '180', label: '180d' },
  { value: '365', label: '1y' },
]

const PATCH_SOFTWARE_TYPES = new Set(['patch', 'update', 'hotfix'])

function classificationBadgeColor(cls: string): { bg: string; text: string } {
  const lower = cls.toLowerCase()
  if (lower === 'critical') return { bg: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', text: 'var(--accent-red)' }
  if (lower === 'security') return { bg: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', text: 'var(--accent-orange)' }
  return { bg: 'var(--bg-subtle)', text: 'var(--text-secondary)' }
}

// ── Main Component ────────────────────────────────────────────────────────────

export function VMDetailPanel({ incidentId, resourceId, resourceName, onClose }: VMDetailPanelProps) {
  const { instance, accounts } = useMsal()
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [vm, setVM] = useState<VMDetail | null>(null)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [metrics, setMetrics] = useState<MetricSeries[]>([])
  const [loading, setLoading] = useState(true)
  const [metricsLoading, setMetricsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [timeRange, setTimeRange] = useState<'PT1H' | 'PT6H' | 'PT24H' | 'P7D'>('PT24H')
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(DEFAULT_METRICS)
  const [metricSelectorOpen, setMetricSelectorOpen] = useState(false)
  const [pollingEvidence, setPollingEvidence] = useState(false)
  const metricsLoadedForTimeRange = useRef<string | null>(null)

  // Arc VMs use a different metric catalog (Log Analytics Perf table)
  const isArcVM = vm?.vm_type === 'Arc VM'
  const activeCatalog = useMemo(() => isArcVM ? ARC_METRIC_CATALOG : METRIC_CATALOG, [isArcVM])
  const activeDefaults = useMemo(() => isArcVM ? ARC_DEFAULT_METRICS : DEFAULT_METRICS, [isArcVM])

  // ── Patch state ──────────────────────────────────────────────────────────
  const [patchSubTab, setPatchSubTab] = useState<PatchSubTab>('pending')
  const [pendingPatches, setPendingPatches] = useState<readonly PendingPatch[]>([])
  const [installedPatches, setInstalledPatches] = useState<readonly InstalledPatch[]>([])
  const [patchLoading, setPatchLoading] = useState(false)
  const [patchError, setPatchError] = useState<string | null>(null)
  const [patchDays, setPatchDays] = useState<DaysOption>('90')
  const patchLoadedRef = useRef(false)

  // ── Panel resize state ───────────────────────────────────────────────────
  const [panelWidth, setPanelWidth] = useState<number>(() => {
    if (typeof window === 'undefined') return PANEL_DEFAULT_WIDTH
    const saved = localStorage.getItem('vmDetailPanelWidth')
    const parsed = saved ? parseInt(saved, 10) : NaN
    return isNaN(parsed) ? PANEL_DEFAULT_WIDTH : Math.min(Math.max(parsed, PANEL_MIN_WIDTH), PANEL_MAX_WIDTH)
  })
  const isDraggingRef = useRef(false)
  const dragStartXRef = useRef(0)
  const dragStartWidthRef = useRef(0)

  const onDragHandleMouseDown = useCallback((e: ReactMouseEvent) => {
    e.preventDefault()
    isDraggingRef.current = true
    dragStartXRef.current = e.clientX
    dragStartWidthRef.current = panelWidth

    const onMouseMove = (ev: MouseEvent) => {
      if (!isDraggingRef.current) return
      const delta = dragStartXRef.current - ev.clientX
      const newWidth = Math.min(Math.max(dragStartWidthRef.current + delta, PANEL_MIN_WIDTH), PANEL_MAX_WIDTH)
      setPanelWidth(newWidth)
    }

    const onMouseUp = () => {
      isDraggingRef.current = false
      setPanelWidth(w => {
        localStorage.setItem('vmDetailPanelWidth', String(w))
        return w
      })
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }, [panelWidth])

  // ── Diagnostic settings state ────────────────────────────────────────────
  const [diagConfigured, setDiagConfigured] = useState<boolean | null>(null)
  const [diagAmaInstalled, setDiagAmaInstalled] = useState<boolean | null>(null)
  const [diagDcrAssociated, setDiagDcrAssociated] = useState<boolean | null>(null)
  const [diagEnabling, setDiagEnabling] = useState(false)
  const [diagError, setDiagError] = useState<string | null>(null)

  // ── Chat state ──────────────────────────────────────────────────────────────
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatStreaming, setChatStreaming] = useState(false)
  const [chatThreadId, setChatThreadId] = useState<string | null>(null)
  const [, setChatRunId] = useState<string | null>(null)
  const chatPollRef = useRef<NodeJS.Timeout | null>(null)
  const chatAutoFired = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

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
      if (res.status === 404) {
        setVM(null)
      } else if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      } else {
        const data = await res.json()
        setVM(data)
      }
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
      metricsLoadedForTimeRange.current = timeRange
    } catch {
      setMetrics([])
    } finally {
      setMetricsLoading(false)
    }
  }, [resourceId, timeRange, selectedMetrics, getAccessToken])

  // Fetch pending patches (ARG-based)
  const fetchPendingPatches = useCallback(async () => {
    if (!resourceId) return
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(
        `/api/proxy/patch/pending?resource_id=${encodeURIComponent(resourceId)}`,
        { headers, signal: AbortSignal.timeout(15000) }
      )
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setPendingPatches(data.patches ?? [])
    } catch (err) {
      setPendingPatches([])
      throw err // let caller handle
    }
  }, [resourceId, getAccessToken])

  // Fetch installed patches (Log Analytics)
  const fetchInstalledPatches = useCallback(async (daysVal: string) => {
    if (!resourceId) return
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(
        `/api/proxy/patch/installed?resource_id=${encodeURIComponent(resourceId)}&days=${daysVal}`,
        { headers, signal: AbortSignal.timeout(15000) }
      )
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setInstalledPatches(
        (data.patches ?? []).filter((p: InstalledPatch) =>
          PATCH_SOFTWARE_TYPES.has(p.SoftwareType.toLowerCase())
        )
      )
    } catch (err) {
      setInstalledPatches([])
      throw err // let caller handle
    }
  }, [resourceId, getAccessToken])

  // Fetch both pending and installed patches
  const fetchAllPatches = useCallback(async (daysVal: string) => {
    setPatchLoading(true)
    setPatchError(null)
    try {
      await Promise.all([
        fetchPendingPatches(),
        fetchInstalledPatches(daysVal),
      ])
    } catch (err) {
      setPatchError(err instanceof Error ? err.message : 'Failed to load patch data')
    } finally {
      setPatchLoading(false)
    }
  }, [fetchPendingPatches, fetchInstalledPatches])

  // ── Diagnostic settings functions ────────────────────────────────────────

  async function fetchDiagSettings() {
    if (!resourceId) return
    try {
      const encoded = encodeResourceId(resourceId)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const osParam = vm?.os_type ? `?os_type=${encodeURIComponent(vm.os_type)}` : ''
      const res = await fetch(`/api/proxy/vms/${encoded}/diagnostic-settings${osParam}`, { headers })
      if (!res.ok) return
      const data = await res.json()
      setDiagAmaInstalled(data.ama_installed ?? false)
      setDiagDcrAssociated(data.dcr_associated ?? false)
      setDiagConfigured(data.configured ?? false)
    } catch {
      // non-fatal — leave diag states as null (unknown)
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
      const osParam = vm?.os_type ? `?os_type=${encodeURIComponent(vm.os_type)}` : ''
      const res = await fetch(`/api/proxy/vms/${encoded}/diagnostic-settings${osParam}`, {
        method: 'POST',
        headers,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.error ?? `HTTP ${res.status}`)
      setDiagAmaInstalled(true)
      setDiagDcrAssociated(true)
      setDiagConfigured(true)
    } catch (err) {
      setDiagError(err instanceof Error ? err.message : 'Failed to enable monitoring')
    } finally {
      setDiagEnabling(false)
    }
  }

  // ── Chat functions ──────────────────────────────────────────────────────────

  function startChatPolling(threadId: string, runId: string) {
    if (chatPollRef.current) clearInterval(chatPollRef.current)

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

  // ── Effects ──────────────────────────────────────────────────────────────────

  // Reset everything when resource changes
  useEffect(() => {
    setActiveTab('overview')
    setVM(null)
    setEvidence(null)
    setMetrics([])
    setLoading(true)
    setError(null)
    setPollingEvidence(false)
    setDiagConfigured(null)
    setDiagAmaInstalled(null)
    setDiagDcrAssociated(null)
    setDiagError(null)
    metricsLoadedForTimeRange.current = null
    setPatchSubTab('pending')
    setPendingPatches([])
    setInstalledPatches([])
    setPatchLoading(false)
    setPatchError(null)
    setPatchDays('90')
    patchLoadedRef.current = false
    setChatMessages([])
    setChatInput('')
    setChatThreadId(null)
    setChatRunId(null)
    chatAutoFired.current = false
    setSelectedMetrics(DEFAULT_METRICS)
  }, [resourceId])

  // Switch metric catalog when VM type is determined (Arc vs Azure)
  useEffect(() => {
    if (vm) {
      setSelectedMetrics(activeDefaults)
      metricsLoadedForTimeRange.current = null
    }
  }, [vm?.vm_type, activeDefaults]) // eslint-disable-line react-hooks/exhaustive-deps

  // Initial fetch when resourceId/incidentId changes
  useEffect(() => {
    if (resourceId) {
      fetchVM()
      fetchEvidence()
    }
  }, [resourceId, incidentId, fetchVM, fetchEvidence])

  // Fetch diagnostic settings AFTER vm data is available (so os_type is correct)
  useEffect(() => {
    if (vm) {
      fetchDiagSettings()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vm])

  // Poll evidence if still pending
  useEffect(() => {
    if (!pollingEvidence) return
    const timer = setInterval(async () => {
      const done = await fetchEvidence()
      if (done) clearInterval(timer)
    }, 5000)
    return () => clearInterval(timer)
  }, [pollingEvidence, fetchEvidence])

  // Lazy-fetch metrics on tab activation; refetch when time range or selectedMetrics changes
  useEffect(() => {
    if (activeTab === 'metrics' && resourceId) {
      fetchMetrics()
    }
    // Lazy-fetch patches on first visit to patches tab
    if (activeTab === 'patches' && resourceId && !patchLoadedRef.current) {
      patchLoadedRef.current = true
      fetchAllPatches(patchDays)
    }
    // Auto-fire chat on first visit to chat tab
    if (activeTab === 'chat' && !chatAutoFired.current && !chatStreaming) {
      chatAutoFired.current = true
      sendChatMessage('Summarize this VM\'s health and suggest investigation steps.')
    }
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  // Refetch installed patches when days selector changes (only if patches tab is active)
  useEffect(() => {
    if (activeTab === 'patches' && resourceId && patchLoadedRef.current) {
      setPatchLoading(true)
      setPatchError(null)
      fetchInstalledPatches(patchDays)
        .catch(err => setPatchError(err instanceof Error ? err.message : 'Failed to load patches'))
        .finally(() => setPatchLoading(false))
    }
  }, [patchDays]) // eslint-disable-line react-hooks/exhaustive-deps

  // Refetch metrics when time range or metric selection changes (only if tab is active)
  useEffect(() => {
    if (activeTab === 'metrics' && resourceId) {
      fetchMetrics()
    }
  }, [timeRange, selectedMetrics]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (chatPollRef.current) clearInterval(chatPollRef.current)
    }
  }, [])

  // Scroll chat to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      className="fixed inset-y-0 right-0 z-40 flex flex-col overflow-hidden"
      style={{
        width: `${panelWidth}px`,
        background: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border)',
        boxShadow: '-4px 0 24px rgba(0,0,0,0.2)',
      }}
    >
      {/* Drag-to-resize handle */}
      <div
        onMouseDown={onDragHandleMouseDown}
        className="absolute left-0 inset-y-0 w-1.5 z-50 cursor-col-resize group"
        title="Drag to resize"
        style={{ touchAction: 'none' }}
      >
        <div
          className="absolute left-0 inset-y-0 w-1.5 opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ background: 'var(--accent-blue)' }}
        />
      </div>

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
            onClick={() => { fetchVM(); fetchEvidence() }}
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

      {/* Tab bar */}
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

        {/* Loading skeleton */}
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
        ) : (

          <>
            {/* ── Overview tab ──────────────────────────────────────────── */}
            {activeTab === 'overview' && (
              <div className="p-4 space-y-4">

                {/* Resource name heading */}
                <div className="mb-1">
                  <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {resourceName ?? 'VM Detail'}
                  </h2>
                  <div className="flex items-center gap-2">
                    <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                      Virtual Machine
                    </p>
                    {vm?.vm_type && (
                      <span
                        className="text-[10px] font-medium px-1.5 py-0.5 rounded"
                        style={{
                          background: vm.vm_type === 'Arc VM'
                            ? 'color-mix(in srgb, var(--accent-purple, #8b5cf6) 15%, transparent)'
                            : 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                          color: vm.vm_type === 'Arc VM'
                            ? 'var(--accent-purple, #8b5cf6)'
                            : 'var(--accent-blue)',
                        }}
                      >
                        {vm.vm_type}
                      </span>
                    )}
                  </div>
                </div>

                {/* Stat cards */}
                {vm ? (
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      {
                        label: 'Power State',
                        value: <PowerBadge state={vm.power_state} />,
                      },
                      {
                        label: 'Health',
                        value: (
                          <span className="flex items-center gap-1">
                            <HealthIcon state={vm.health_state} />
                            <span className="text-sm font-semibold" style={{ color: HealthColor(vm.health_state) }}>
                              {vm.health_state}
                            </span>
                          </span>
                        ),
                      },
                      {
                        label: 'AMA Status',
                        value: diagConfigured === null
                          ? <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Checking…</span>
                          : diagConfigured
                            ? <span className="text-xs font-medium" style={{ color: 'var(--accent-green)' }}>Active</span>
                            : <span className="text-xs font-medium" style={{ color: 'var(--accent-orange)' }}>Not configured</span>,
                      },
                      {
                        label: 'Active Alerts',
                        value: (
                          <span
                            className="text-lg font-semibold"
                            style={{ color: vm.active_incidents.length > 0 ? 'var(--accent-red)' : 'var(--text-muted)' }}
                          >
                            {vm.active_incidents.length}
                          </span>
                        ),
                      },
                    ].map(card => (
                      <div
                        key={card.label}
                        className="p-3 rounded-lg"
                        style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                      >
                        <p className="text-[11px] uppercase tracking-wide mb-1" style={{ color: 'var(--text-muted)' }}>
                          {card.label}
                        </p>
                        <div>{card.value}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div
                    className="p-3 rounded-lg"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                      {resourceName || 'Resource Detail'}
                    </p>
                    <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                      Live VM data unavailable (resource not found in Azure Resource Graph)
                    </p>
                  </div>
                )}

                {/* VM metadata */}
                {vm && (
                  <div
                    className="rounded-lg p-3"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                      Details
                    </p>
                    {[
                      ['Resource Group', vm.resource_group],
                      ['Location', vm.location],
                      ['Size', vm.size],
                      ['OS', vm.os_name || vm.os_type],
                      ['Subscription', vm.subscription_id],
                    ].map(([k, v]) => (
                      <div
                        key={k}
                        className="flex justify-between py-1 text-xs"
                        style={{ borderBottom: '1px solid var(--border-subtle)' }}
                      >
                        <span style={{ color: 'var(--text-secondary)' }}>{k}</span>
                        <span className="font-mono truncate max-w-[55%] text-right" style={{ color: 'var(--text-primary)' }}>
                          {v || '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Active incidents */}
                {vm && vm.active_incidents.length > 0 && (
                  <div
                    className="rounded-lg p-3"
                    style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                  >
                    <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-muted)' }}>
                      Active Incidents ({vm.active_incidents.length})
                    </p>
                    {vm.active_incidents.map((inc: ActiveIncident) => (
                      <div
                        key={inc.incident_id}
                        className="flex items-center justify-between py-1.5 text-xs"
                        style={{ borderBottom: '1px solid var(--border-subtle)' }}
                      >
                        <span className="truncate flex-1 mr-2" style={{ color: 'var(--text-secondary)' }}>
                          {inc.title ?? inc.incident_id}
                        </span>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <SeverityBadge severity={inc.severity} />
                          <span style={{ color: 'var(--text-muted)' }}>
                            {new Date(inc.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

              </div>
            )}

            {/* ── Metrics tab ───────────────────────────────────────────── */}
            {activeTab === 'metrics' && (
              <div className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>Azure Monitor Metrics</p>
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
                            maxHeight: '420px',
                            background: 'var(--bg-surface)',
                            border: '1px solid var(--border)',
                          }}
                        >
                          <div className="px-3 py-2 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
                            <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>Select metrics</span>
                            <div className="flex gap-2">
                              <button
                                onClick={() => setSelectedMetrics(activeCatalog.map(m => m.name))}
                                className="text-[10px] cursor-pointer hover:opacity-70"
                                style={{ color: 'var(--accent-blue)' }}
                              >All</button>
                              <button
                                onClick={() => setSelectedMetrics(activeDefaults)}
                                className="text-[10px] cursor-pointer hover:opacity-70"
                                style={{ color: 'var(--text-muted)' }}
                              >Reset</button>
                            </div>
                          </div>
                          {(['CPU', 'Memory', 'Disk', 'Network', 'Availability'] as const).map(group => (
                            <div key={group}>
                              <div className="px-3 pt-2 pb-1 text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                {group}
                              </div>
                              {activeCatalog.filter(m => m.group === group).map(m => (
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
                  <div className="py-8 text-center">
                    <Activity className="h-8 w-8 mx-auto mb-2" style={{ color: 'var(--text-muted)' }} />
                    <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                      {vm?.power_state === 'deallocated'
                        ? 'No metrics — VM is deallocated. Start the VM to collect data.'
                        : vm?.vm_type === 'Arc VM'
                        ? 'No Perf data in Log Analytics yet. Ensure Azure Monitor Agent is active and a Data Collection Rule is collecting performance counters.'
                        : 'No metrics available'}
                    </p>
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
                              {activeCatalog.find(c => c.name === m.name)?.label ?? m.name ?? '—'}
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

                {/* Diagnostic settings status */}
                {isArcVM && metrics.length > 0 && (
                  <div className="mt-2 text-[11px] flex items-center gap-1" style={{ color: 'var(--text-muted)' }}>
                    Source: Log Analytics Perf table
                  </div>
                )}
                {diagConfigured === true && (
                  <div className="mt-2 text-[11px] flex items-center gap-1" style={{ color: 'var(--accent-green)' }}>
                    ✓ Azure Monitor Agent active — collecting data to Log Analytics
                  </div>
                )}
                {diagAmaInstalled === true && diagDcrAssociated === false && (
                  <div
                    className="mt-3 rounded-md p-2 text-xs flex items-start justify-between gap-2"
                    style={{ background: `color-mix(in srgb, var(--accent-orange) 8%, transparent)`, border: '1px solid color-mix(in srgb, var(--accent-orange) 20%, transparent)' }}
                  >
                    <span style={{ color: 'var(--text-secondary)' }}>
                      AMA installed, no data collection rule — click Enable to link a DCR.
                    </span>
                    <button
                      onClick={enableDiagSettings}
                      disabled={diagEnabling}
                      className="flex-shrink-0 px-2 py-1 rounded text-[11px] font-medium cursor-pointer disabled:opacity-50"
                      style={{ background: 'var(--accent-orange)', color: 'white' }}
                    >
                      {diagEnabling ? 'Enabling…' : 'Enable'}
                    </button>
                  </div>
                )}
                {diagConfigured === false && diagAmaInstalled === false && (
                  <div
                    className="mt-3 rounded-md p-2 text-xs flex items-start justify-between gap-2"
                    style={{ background: `color-mix(in srgb, var(--accent-blue) 8%, transparent)`, border: '1px solid color-mix(in srgb, var(--accent-blue) 20%, transparent)' }}
                  >
                    <span style={{ color: 'var(--text-secondary)' }}>
                      Enable monitoring — installs Azure Monitor Agent and Data Collection Rule.
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
                {diagError && (
                  <div className="mt-1 text-xs" style={{ color: 'var(--accent-red)' }}>{diagError}</div>
                )}
              </div>
            )}

            {/* ── Evidence tab ──────────────────────────────────────────── */}
            {activeTab === 'evidence' && (
              <div className="p-4">
                {!incidentId ? (
                  <div className="py-12 text-center">
                    <AlertTriangle className="h-8 w-8 mx-auto mb-2" style={{ color: 'var(--text-muted)' }} />
                    <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                      No incident selected
                    </p>
                    <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                      Open a specific alert to view diagnostic evidence.
                    </p>
                  </div>
                ) : pollingEvidence && !evidence ? (
                  <div className="flex items-center gap-2 text-sm pt-4" style={{ color: 'var(--text-secondary)' }}>
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Collecting evidence… (typically ~15s)
                  </div>
                ) : evidence?.evidence_summary ? (
                  <div className="space-y-3">
                    {/* Metric anomalies */}
                    {evidence.evidence_summary.metric_anomalies.length > 0 && (
                      <div
                        className="rounded-lg p-3"
                        style={{
                          background: `color-mix(in srgb, var(--accent-orange) 8%, transparent)`,
                          border: '1px solid color-mix(in srgb, var(--accent-orange) 20%, transparent)',
                        }}
                      >
                        <p className="text-xs font-semibold mb-2" style={{ color: 'var(--accent-orange)' }}>
                          Metric Anomalies ({evidence.evidence_summary.metric_anomalies.length})
                        </p>
                        {evidence.evidence_summary.metric_anomalies.slice(0, 3).map((a, i) => (
                          <div key={i} className="text-xs py-0.5" style={{ color: 'var(--text-secondary)' }}>
                            {a.metric_name}: {a.current_value != null ? a.current_value.toFixed(1) : '—'} {a.unit} (threshold: {a.threshold})
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Recent changes */}
                    {evidence.evidence_summary.recent_changes.length > 0 && (
                      <div
                        className="rounded-lg p-3"
                        style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                      >
                        <p className="text-xs font-semibold mb-2" style={{ color: 'var(--text-secondary)' }}>
                          Recent Changes (last 2h)
                        </p>
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
                        className="rounded-lg p-3 text-xs"
                        style={{
                          background: `color-mix(in srgb, var(--accent-red) 8%, transparent)`,
                          border: '1px solid color-mix(in srgb, var(--accent-red) 20%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {evidence.evidence_summary.log_errors.count} log errors detected
                      </div>
                    )}

                    {/* No anomalies */}
                    {evidence.evidence_summary.metric_anomalies.length === 0 &&
                     evidence.evidence_summary.recent_changes.length === 0 &&
                     evidence.evidence_summary.log_errors.count === 0 && (
                      <div className="py-8 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
                        No anomalies detected in the last 2 hours.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="py-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                    No evidence data available.
                  </div>
                )}
              </div>
            )}

            {/* ── Patches tab ───────────────────────────────────────────── */}
            {activeTab === 'patches' && (
              <div className="p-4 space-y-3">

                {/* Summary stat chips */}
                {(() => {
                  const criticalCount = pendingPatches.filter(p =>
                    p.classifications.some(c => c.toLowerCase() === 'critical')
                  ).length
                  const securityCount = pendingPatches.filter(p =>
                    p.classifications.some(c => c.toLowerCase() === 'security')
                  ).length
                  const rebootRequired = pendingPatches.some(p => p.rebootRequired)

                  return (
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        {
                          label: 'Pending',
                          value: patchLoading ? '…' : String(pendingPatches.length),
                          color: pendingPatches.length > 0 ? 'var(--accent-orange)' : 'var(--text-primary)',
                        },
                        {
                          label: 'Critical',
                          value: patchLoading ? '…' : String(criticalCount),
                          color: criticalCount > 0 ? 'var(--accent-red)' : 'var(--text-primary)',
                        },
                        {
                          label: 'Security',
                          value: patchLoading ? '…' : String(securityCount),
                          color: securityCount > 0 ? 'var(--accent-orange)' : 'var(--text-primary)',
                        },
                      ].map(chip => (
                        <div
                          key={chip.label}
                          className="flex flex-col items-center rounded-lg p-2"
                          style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                        >
                          <span className="font-mono text-base font-semibold" style={{ color: chip.color }}>
                            {chip.value}
                          </span>
                          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{chip.label}</span>
                        </div>
                      ))}
                      <div
                        className="flex flex-col items-center rounded-lg p-2"
                        style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                      >
                        <span className="font-mono text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
                          {patchLoading ? '…' : String(installedPatches.length)}
                        </span>
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Installed</span>
                      </div>
                      <div
                        className="flex flex-col items-center rounded-lg p-2 col-span-2"
                        style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                      >
                        <span
                          className="font-mono text-base font-semibold"
                          style={{ color: rebootRequired ? 'var(--accent-orange)' : 'var(--text-primary)' }}
                        >
                          {patchLoading ? '…' : rebootRequired ? 'Yes' : 'No'}
                        </span>
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Reboot Required</span>
                      </div>
                    </div>
                  )
                })()}

                {/* Sub-tab toggle + days selector */}
                <div className="flex items-center gap-0" style={{ borderBottom: '1px solid var(--border)' }}>
                  <button
                    onClick={() => setPatchSubTab('pending')}
                    className="flex items-center gap-1 px-3 py-2 text-[11px] font-semibold transition-colors cursor-pointer"
                    style={{
                      borderBottom: patchSubTab === 'pending' ? '2px solid var(--accent-blue)' : '2px solid transparent',
                      color: patchSubTab === 'pending' ? 'var(--accent-blue)' : 'var(--text-muted)',
                      marginBottom: '-1px',
                      background: 'transparent',
                    }}
                  >
                    <ShieldAlert className="h-3 w-3" />
                    Pending
                    {pendingPatches.length > 0 && (
                      <span
                        className="text-[9px] px-1 py-0 rounded-full font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {pendingPatches.length}
                      </span>
                    )}
                  </button>
                  <button
                    onClick={() => setPatchSubTab('installed')}
                    className="flex items-center gap-1 px-3 py-2 text-[11px] font-semibold transition-colors cursor-pointer"
                    style={{
                      borderBottom: patchSubTab === 'installed' ? '2px solid var(--accent-blue)' : '2px solid transparent',
                      color: patchSubTab === 'installed' ? 'var(--accent-blue)' : 'var(--text-muted)',
                      marginBottom: '-1px',
                      background: 'transparent',
                    }}
                  >
                    <Package className="h-3 w-3" />
                    Installed
                    {installedPatches.length > 0 && (
                      <span
                        className="text-[9px] px-1 py-0 rounded-full font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                          color: 'var(--accent-blue)',
                        }}
                      >
                        {installedPatches.length}
                      </span>
                    )}
                  </button>
                  {patchSubTab === 'installed' && (
                    <div className="ml-auto flex items-center gap-1">
                      {DAYS_OPTIONS.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => setPatchDays(opt.value)}
                          className="text-[10px] px-1.5 py-0.5 rounded cursor-pointer"
                          style={{
                            background: patchDays === opt.value ? 'var(--accent-blue)' : 'var(--bg-subtle)',
                            color: patchDays === opt.value ? 'white' : 'var(--text-secondary)',
                          }}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Patch content */}
                {patchLoading ? (
                  <div className="space-y-2">
                    {[...Array(4)].map((_, i) => (
                      <div key={i} className="h-10 rounded animate-pulse" style={{ background: 'var(--bg-subtle)' }} />
                    ))}
                  </div>
                ) : patchError ? (
                  <div className="py-8 text-center">
                    <AlertTriangle className="h-6 w-6 mx-auto mb-2" style={{ color: 'var(--accent-red)' }} />
                    <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{patchError}</p>
                    <button
                      onClick={() => fetchAllPatches(patchDays)}
                      className="mt-2 text-xs px-3 py-1 rounded cursor-pointer"
                      style={{ background: 'var(--bg-subtle)', color: 'var(--accent-blue)' }}
                    >
                      Retry
                    </button>
                  </div>
                ) : patchSubTab === 'pending' ? (
                  pendingPatches.length === 0 ? (
                    <div className="py-8 text-center">
                      <CheckCircle className="h-6 w-6 mx-auto mb-2" style={{ color: 'var(--accent-green)' }} />
                      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        No pending patches. This VM is up to date.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      {pendingPatches.map((p, idx) => (
                        <div
                          key={`${p.patchName}-${idx}`}
                          className="rounded-md p-2.5"
                          style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-xs font-medium truncate flex-1" style={{ color: 'var(--text-primary)' }} title={p.patchName}>
                              {p.patchName}
                            </p>
                            {p.kbid && (
                              <span className="text-[10px] font-mono flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
                                {p.kbid.toUpperCase().startsWith('KB') ? p.kbid : `KB${p.kbid}`}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                            {p.classifications.map(cls => {
                              const c = classificationBadgeColor(cls)
                              return (
                                <span
                                  key={cls}
                                  className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                                  style={{ background: c.bg, color: c.text }}
                                >
                                  {cls}
                                </span>
                              )
                            })}
                            {p.version && (
                              <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                v{p.version}
                              </span>
                            )}
                            {p.rebootRequired && (
                              <span
                                className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                                style={{
                                  background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
                                  color: 'var(--accent-orange)',
                                }}
                              >
                                Reboot
                              </span>
                            )}
                          </div>
                          {p.cves && p.cves.length > 0 && (
                            <div className="mt-1.5">
                              <CveBadges cves={p.cves} />
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )
                ) : (
                  installedPatches.length === 0 ? (
                    <div className="py-8 text-center">
                      <Package className="h-6 w-6 mx-auto mb-2" style={{ color: 'var(--text-muted)' }} />
                      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        No installed patches recorded in the last {patchDays} days.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      {installedPatches.map((p, idx) => {
                        const kbMatch = /KB(\d+)/i.exec(p.SoftwareName)
                        const kbId = kbMatch ? `KB${kbMatch[1]}` : null
                        const c = classificationBadgeColor(p.Category)
                        return (
                          <div
                            key={`${p.SoftwareName}-${p.CurrentVersion}-${idx}`}
                            className="rounded-md p-2.5"
                            style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-xs font-medium truncate flex-1" style={{ color: 'var(--text-primary)' }} title={p.SoftwareName}>
                                {p.SoftwareName}
                              </p>
                              {kbId && (
                                <span className="text-[10px] font-mono flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
                                  {kbId}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                              <span
                                className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                                style={{ background: c.bg, color: c.text }}
                              >
                                {p.Category || 'Other'}
                              </span>
                              {p.CurrentVersion && (
                                <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                  v{p.CurrentVersion}
                                </span>
                              )}
                              {p.InstalledDate && (
                                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                  {new Date(p.InstalledDate).toLocaleDateString()}
                                </span>
                              )}
                            </div>
                            {p.cves && p.cves.length > 0 && (
                              <div className="mt-1.5">
                                <CveBadges cves={p.cves} />
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )
                )}
              </div>
            )}

            {/* ── AI Chat tab ───────────────────────────────────────────── */}
            {activeTab === 'chat' && (
              <div className="flex flex-col" style={{ height: '100%' }}>
                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {chatMessages.map((msg, i) => (
                    <div
                      key={i}
                      className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
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
                      )}
                    </div>
                  ))}
                  {chatStreaming && (
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
                    placeholder="Ask about this VM…"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        sendChatMessage(chatInput)
                      }
                    }}
                    disabled={chatStreaming}
                    className="flex-1 text-xs px-3 py-2 rounded-md outline-none"
                    style={{
                      background: 'var(--bg-canvas)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                    }}
                  />
                  <button
                    onClick={() => sendChatMessage(chatInput)}
                    disabled={chatStreaming || !chatInput.trim()}
                    className="px-3 py-2 rounded-md text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ background: 'var(--accent-blue)', color: '#fff' }}
                  >
                    Send
                  </button>
                </div>
              </div>
            )}

          </>
        )}
      </div>
    </div>
  )
}
