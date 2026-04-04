'use client'

import { useState, useEffect, useCallback } from 'react'
import { Server, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'

interface VMRow {
  id: string
  name: string
  resource_group: string
  subscription_id: string
  location: string
  size: string
  os_type: string
  os_name: string
  power_state: string
  vm_type: string  // "Azure VM" | "Arc VM"
  health_state: string
  ama_status: string
  active_alert_count: number
}

interface VMTabProps {
  subscriptions: string[]
  onVMClick?: (resourceId: string, resourceName: string) => void
}

function PowerStateBadge({ state }: { state: string }) {
  const config = {
    running: { label: 'Running', color: 'var(--accent-green)' },
    stopped: { label: 'Stopped', color: 'var(--accent-yellow)' },
    deallocated: { label: 'Deallocated', color: 'var(--text-muted)' },
  }[state.toLowerCase()] ?? { label: state, color: 'var(--text-muted)' }

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${config.color} 15%, transparent)`,
        color: config.color,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: config.color }} />
      {config.label}
    </span>
  )
}

function HealthBadge({ state }: { state: string }) {
  const config = {
    available: { label: 'Healthy', color: 'var(--accent-green)' },
    degraded: { label: 'Degraded', color: 'var(--accent-orange)' },
    unavailable: { label: 'Unavailable', color: 'var(--accent-red)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
  }[state.toLowerCase()] ?? { label: state, color: 'var(--text-muted)' }

  return (
    <span
      className="text-[11px] font-medium"
      style={{ color: config.color }}
    >
      {config.label}
    </span>
  )
}

function VMTypeBadge({ vmType }: { vmType: string }) {
  const isArc = vmType === 'Arc VM'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: isArc
          ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
          : 'var(--bg-subtle)',
        color: isArc ? 'var(--accent-blue)' : 'var(--text-muted)',
      }}
    >
      {isArc ? 'Arc' : 'Azure'}
    </span>
  )
}

export function VMTab({ subscriptions, onVMClick }: VMTabProps) {
  const { instance, accounts } = useMsal()
  const [vms, setVMs] = useState<VMRow[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

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

  async function fetchVMs() {
    if (subscriptions.length === 0) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ subscriptions: subscriptions.join(',') })
      if (search) params.set('search', search)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vms?${params}`, { headers })
      const data = await res.json()
      setVMs(data.vms ?? [])
    } catch {
      setError('Failed to load VMs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchVMs() }, [subscriptions]) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = vms.filter(vm =>
    !search || vm.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Virtual Machines
          </span>
          {!loading && (
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                background: 'var(--bg-subtle)',
                color: 'var(--text-secondary)',
              }}
            >
              {filtered.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search VMs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-md outline-none"
            style={{
              background: 'var(--bg-canvas)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              width: '180px',
            }}
          />
          <button
            onClick={fetchVMs}
            disabled={loading}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh VM list"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Content */}
      {error ? (
        <div className="p-8 text-center text-sm" style={{ color: 'var(--accent-red)' }}>
          {error}
        </div>
      ) : loading ? (
        <div className="p-8">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex gap-4 mb-3 animate-pulse">
              <div className="h-4 rounded flex-1" style={{ background: 'var(--bg-subtle)' }} />
              <div className="h-4 rounded w-24" style={{ background: 'var(--bg-subtle)' }} />
              <div className="h-4 rounded w-20" style={{ background: 'var(--bg-subtle)' }} />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="p-12 text-center">
          <Server className="h-8 w-8 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {subscriptions.length === 0
              ? 'Select a subscription to view VMs'
              : 'No VMs found in selected subscriptions'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Name', 'Resource Group', 'Size', 'OS', 'Type', 'Power State', 'Health', 'Alerts'].map(col => (
                  <th
                    key={col}
                    className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(vm => (
                <tr
                  key={vm.id}
                  className="cursor-pointer transition-colors"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  onClick={() => onVMClick?.(vm.id, vm.name)}
                >
                  <td className="px-4 py-3 font-mono text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                    {vm.name}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vm.resource_group}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vm.size || '—'}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vm.os_name || vm.os_type}
                  </td>
                  <td className="px-4 py-3">
                    <VMTypeBadge vmType={vm.vm_type ?? 'Azure VM'} />
                  </td>
                  <td className="px-4 py-3">
                    <PowerStateBadge state={vm.power_state} />
                  </td>
                  <td className="px-4 py-3">
                    <HealthBadge state={vm.health_state} />
                  </td>
                  <td className="px-4 py-3">
                    {vm.active_alert_count > 0 ? (
                      <span
                        className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {vm.active_alert_count}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
