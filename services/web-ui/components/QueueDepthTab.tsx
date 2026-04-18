'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { MessageSquare, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'

interface QueueNamespace {
  namespace_id: string
  arm_id: string
  name: string
  namespace_type: string
  resource_group: string
  subscription_id: string
  location: string
  sku_name: string
  status: string
  active_messages: number | null
  dead_letter_messages: number | null
  health_status: string
  health_reason: string
  scanned_at: string
}

interface QueueSummary {
  total: number
  critical: number
  warning: number
  healthy: number
  total_dead_letter: number
  total_active_messages: number
}

interface QueueDepthTabProps {
  subscriptions?: string[]
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function NamespaceTypeBadge({ nsType }: { nsType: string }) {
  const label = nsType === 'service_bus' ? 'Service Bus' : 'Event Hub'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
      }}
    >
      {label}
    </span>
  )
}

function HealthBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string }> = {
    healthy: { label: 'Healthy', color: 'var(--accent-green)' },
    warning: { label: 'Warning', color: 'var(--accent-yellow)' },
    critical: { label: 'Critical', color: 'var(--accent-red)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
  }
  const { label, color } = config[status] ?? { label: status, color: 'var(--text-muted)' }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {label}
    </span>
  )
}

function DeadLetterCount({ count }: { count: number | null }) {
  if (count === null) {
    return <span style={{ color: 'var(--text-muted)' }}>—</span>
  }
  const color = count > 10 ? 'var(--accent-red)' : count > 0 ? 'var(--accent-yellow)' : 'var(--text-primary)'
  return (
    <span className="font-medium" style={{ color }}>{count.toLocaleString()}</span>
  )
}

// ---------------------------------------------------------------------------
// Summary strip
// ---------------------------------------------------------------------------

function SummaryStrip({ summary }: { summary: QueueSummary }) {
  const items = [
    { label: 'Total', value: summary.total, color: 'var(--text-primary)' },
    { label: 'Critical DLQ', value: summary.critical, color: 'var(--accent-red)' },
    { label: 'Warning', value: summary.warning, color: 'var(--accent-yellow)' },
    { label: 'Healthy', value: summary.healthy, color: 'var(--accent-green)' },
    { label: 'Active msgs', value: summary.total_active_messages.toLocaleString(), color: 'var(--text-primary)' },
    { label: 'Dead-letter', value: summary.total_dead_letter.toLocaleString(), color: summary.total_dead_letter > 0 ? 'var(--accent-red)' : 'var(--text-primary)' },
  ]
  return (
    <div className="flex flex-wrap gap-4 px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
      {items.map(({ label, value, color }) => (
        <div key={label} className="flex flex-col items-center min-w-[80px]">
          <span className="text-xl font-bold" style={{ color }}>{value}</span>
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{label}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function QueueDepthTab({ subscriptions = [] }: QueueDepthTabProps) {
  const { instance, accounts } = useMsal()
  const [namespaces, setNamespaces] = useState<QueueNamespace[]>([])
  const [summary, setSummary] = useState<QueueSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [healthFilter, setHealthFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

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

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`

      const params = new URLSearchParams()
      if (subscriptions.length > 0) params.set('subscription_id', subscriptions[0])
      if (healthFilter) params.set('health_status', healthFilter)
      if (typeFilter) params.set('namespace_type', typeFilter)

      const [nsRes, sumRes] = await Promise.all([
        fetch(`/api/proxy/queues?${params}`, { headers }),
        fetch('/api/proxy/queues/summary', { headers }),
      ])

      const nsData = await nsRes.json()
      const sumData = await sumRes.json()

      if (!nsRes.ok) {
        setError(nsData?.error ?? `Failed to load queues (${nsRes.status})`)
      } else {
        setNamespaces(nsData.namespaces ?? [])
      }
      if (sumRes.ok) setSummary(sumData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken, subscriptions, healthFilter, typeFilter])

  useEffect(() => {
    fetchData()
    timerRef.current = setInterval(fetchData, 5 * 60 * 1000) // 5-min auto-refresh
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchData])

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--bg-canvas)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4" style={{ color: 'var(--accent-blue)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Queue Depth
          </span>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="text-xs rounded px-2 py-1"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
          >
            <option value="">All Types</option>
            <option value="service_bus">Service Bus</option>
            <option value="event_hub">Event Hub</option>
          </select>
          <select
            className="text-xs rounded px-2 py-1"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
            value={healthFilter}
            onChange={e => setHealthFilter(e.target.value)}
          >
            <option value="">All Health</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="healthy">Healthy</option>
            <option value="unknown">Unknown</option>
          </select>
          <button
            onClick={() => void fetchData()}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded font-medium disabled:opacity-50"
            style={{ background: 'var(--accent-blue)', color: '#fff' }}
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary strip */}
      {summary && <SummaryStrip summary={summary} />}

      {/* Error */}
      {error && (
        <div className="mx-4 mt-3 px-3 py-2 rounded text-xs" style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', color: 'var(--accent-red)' }}>
          {error}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading && namespaces.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-sm" style={{ color: 'var(--text-muted)' }}>
            Loading…
          </div>
        ) : namespaces.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-sm" style={{ color: 'var(--text-muted)' }}>
            No queue data found.
          </div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
                {['Name', 'Type', 'SKU', 'Active msgs', 'Dead-letter', 'Status', 'Health'].map(h => (
                  <th key={h} className="text-left px-4 py-2 text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {namespaces.map(ns => (
                <tr
                  key={ns.namespace_id}
                  style={{ borderBottom: '1px solid var(--border)' }}
                  className="hover:bg-[color-mix(in_srgb,var(--accent-blue)_4%,transparent)]"
                >
                  <td className="px-4 py-2">
                    <div className="font-medium text-[13px]" style={{ color: 'var(--text-primary)' }}>{ns.name}</div>
                    <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{ns.resource_group}</div>
                  </td>
                  <td className="px-4 py-2"><NamespaceTypeBadge nsType={ns.namespace_type} /></td>
                  <td className="px-4 py-2">
                    <span className="text-[12px]" style={{ color: 'var(--text-primary)' }}>{ns.sku_name || '—'}</span>
                  </td>
                  <td className="px-4 py-2">
                    {ns.active_messages !== null
                      ? <span style={{ color: 'var(--text-primary)' }}>{ns.active_messages.toLocaleString()}</span>
                      : <span style={{ color: 'var(--text-muted)' }}>—</span>
                    }
                  </td>
                  <td className="px-4 py-2">
                    <DeadLetterCount count={ns.dead_letter_messages} />
                  </td>
                  <td className="px-4 py-2">
                    <span className="text-[12px]" style={{ color: ns.status === 'Active' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {ns.status}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <div><HealthBadge status={ns.health_status} /></div>
                    {ns.health_reason && ns.health_status !== 'healthy' && (
                      <div className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{ns.health_reason}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
