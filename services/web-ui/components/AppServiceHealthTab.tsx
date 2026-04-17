'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Globe, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'

interface AppServiceApp {
  app_id: string
  arm_id: string
  name: string
  app_type: string
  resource_group: string
  subscription_id: string
  location: string
  state: string
  enabled: boolean
  https_only: boolean
  min_tls_version: string
  sku_name: string
  health_status: string
  issues: string[]
  scanned_at: string
}

interface AppServiceSummary {
  total: number
  healthy: number
  stopped: number
  misconfigured: number
  https_only_violations: number
  tls_violations: number
  free_tier_count: number
}

interface AppServiceHealthTabProps {
  subscriptions?: string[]
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

function AppTypeBadge({ appType }: { appType: string }) {
  const labels: Record<string, string> = {
    web_app: 'Web App',
    function_app: 'Function App',
    logic_app: 'Logic App',
    app_service_plan: 'Plan',
  }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
      }}
    >
      {labels[appType] ?? appType}
    </span>
  )
}

function HttpsBadge({ httpsOnly }: { httpsOnly: boolean }) {
  const color = httpsOnly ? 'var(--accent-green)' : 'var(--accent-red)'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {httpsOnly ? 'HTTPS' : 'HTTP'}
    </span>
  )
}

function TlsBadge({ version }: { version: string }) {
  const weak = version === '1.0' || version === '1.1'
  const color = weak ? 'var(--accent-red)' : version ? 'var(--accent-green)' : 'var(--text-muted)'
  const label = version ? `TLS ${version}` : '—'
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

function HealthBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string }> = {
    healthy: { label: 'Healthy', color: 'var(--accent-green)' },
    stopped: { label: 'Stopped', color: 'var(--accent-red)' },
    misconfigured: { label: 'Misconfigured', color: 'var(--accent-yellow)' },
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

// ---------------------------------------------------------------------------
// Summary strip
// ---------------------------------------------------------------------------

function SummaryStrip({ summary }: { summary: AppServiceSummary }) {
  const items = [
    { label: 'Total', value: summary.total, color: 'var(--text-primary)' },
    { label: 'Healthy', value: summary.healthy, color: 'var(--accent-green)' },
    { label: 'Stopped', value: summary.stopped, color: 'var(--accent-red)' },
    { label: 'Misconfigured', value: summary.misconfigured, color: 'var(--accent-yellow)' },
    { label: 'HTTPS violations', value: summary.https_only_violations, color: 'var(--accent-red)' },
    { label: 'TLS violations', value: summary.tls_violations, color: 'var(--accent-red)' },
    { label: 'Free tier', value: summary.free_tier_count, color: 'var(--accent-yellow)' },
  ]
  return (
    <div className="flex flex-wrap gap-4 px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
      {items.map(({ label, value, color }) => (
        <div key={label} className="flex flex-col items-center min-w-[72px]">
          <span className="text-xl font-bold" style={{ color }}>{value}</span>
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{label}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Issues expand row
// ---------------------------------------------------------------------------

function IssuesCell({ issues }: { issues: string[] }) {
  const [open, setOpen] = useState(false)
  if (!issues || issues.length === 0) {
    return <span style={{ color: 'var(--text-muted)' }}>—</span>
  }
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="text-[12px] font-medium underline underline-offset-2 cursor-pointer"
        style={{ color: 'var(--accent-yellow)' }}
      >
        {issues.length} issue{issues.length > 1 ? 's' : ''}
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5">
          {issues.map((issue, i) => (
            <li key={i} className="text-[11px]" style={{ color: 'var(--accent-yellow)' }}>
              • {issue}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AppServiceHealthTab({ subscriptions = [] }: AppServiceHealthTabProps) {
  const { instance, accounts } = useMsal()
  const [apps, setApps] = useState<AppServiceApp[]>([])
  const [summary, setSummary] = useState<AppServiceSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [healthFilter, setHealthFilter] = useState('')
  const [appTypeFilter, setAppTypeFilter] = useState('')
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
      if (appTypeFilter) params.set('app_type', appTypeFilter)

      const [appsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/app-services?${params}`, { headers }),
        fetch('/api/proxy/app-services/summary', { headers }),
      ])

      const appsData = await appsRes.json()
      const summaryData = await summaryRes.json()

      if (!appsRes.ok) {
        setError(appsData?.error ?? `Failed to load app services (${appsRes.status})`)
      } else {
        setApps(appsData.apps ?? [])
      }
      if (summaryRes.ok) {
        setSummary(summaryData)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [getAccessToken, subscriptions, healthFilter, appTypeFilter])

  useEffect(() => {
    fetchData()
    timerRef.current = setInterval(fetchData, 10 * 60 * 1000) // 10-min auto-refresh
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      await fetch('/api/proxy/app-services/scan', { method: 'POST', headers })
      await fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const filtered = apps

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--bg-canvas)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <Globe className="w-4 h-4" style={{ color: 'var(--accent-blue)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            App Service Health
          </span>
        </div>
        <div className="flex items-center gap-3">
          {/* Filters */}
          <select
            className="text-xs rounded px-2 py-1"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
            value={appTypeFilter}
            onChange={e => setAppTypeFilter(e.target.value)}
          >
            <option value="">All Types</option>
            <option value="web_app">Web App</option>
            <option value="function_app">Function App</option>
            <option value="logic_app">Logic App</option>
            <option value="app_service_plan">Plan</option>
          </select>
          <select
            className="text-xs rounded px-2 py-1"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}
            value={healthFilter}
            onChange={e => setHealthFilter(e.target.value)}
          >
            <option value="">All Health</option>
            <option value="healthy">Healthy</option>
            <option value="stopped">Stopped</option>
            <option value="misconfigured">Misconfigured</option>
          </select>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded font-medium disabled:opacity-50"
            style={{ background: 'var(--accent-blue)', color: '#fff' }}
          >
            <RefreshCw className={`w-3 h-3 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning…' : 'Scan'}
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
        {loading && filtered.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-sm" style={{ color: 'var(--text-muted)' }}>
            Loading…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-sm" style={{ color: 'var(--text-muted)' }}>
            No app services found. Run a scan to populate data.
          </div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
                {['Name', 'Type', 'State', 'HTTPS', 'TLS', 'SKU', 'Issues'].map(h => (
                  <th key={h} className="text-left px-4 py-2 text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(app => (
                <tr
                  key={app.app_id}
                  style={{ borderBottom: '1px solid var(--border)' }}
                  className="hover:bg-[color-mix(in_srgb,var(--accent-blue)_4%,transparent)]"
                >
                  <td className="px-4 py-2">
                    <div className="font-medium text-[13px]" style={{ color: 'var(--text-primary)' }}>{app.name}</div>
                    <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{app.resource_group}</div>
                  </td>
                  <td className="px-4 py-2"><AppTypeBadge appType={app.app_type} /></td>
                  <td className="px-4 py-2">
                    <span className="text-[12px]" style={{ color: app.state === 'Running' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {app.state}
                    </span>
                  </td>
                  <td className="px-4 py-2"><HttpsBadge httpsOnly={app.https_only} /></td>
                  <td className="px-4 py-2"><TlsBadge version={app.min_tls_version} /></td>
                  <td className="px-4 py-2">
                    <span className="text-[12px]" style={{ color: 'var(--text-primary)' }}>{app.sku_name || '—'}</span>
                  </td>
                  <td className="px-4 py-2"><IssuesCell issues={app.issues} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
