'use client'

import { useState, useEffect, useCallback } from 'react'
import { Scaling, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { VMSSRow } from '@/types/azure-resources'

interface VMSSTabProps {
  subscriptions: string[]
  onVMSSClick?: (resourceId: string, resourceName: string) => void
}

function InstanceCountBadge({ total, healthy }: { total: number; healthy: number }) {
  const unhealthy = total - healthy
  const ratio = total > 0 ? unhealthy / total : 0
  let color: string
  if (unhealthy === 0) {
    color = 'var(--accent-green)'
  } else if (ratio > 0.2) {
    color = 'var(--accent-red)'
  } else {
    color = 'var(--accent-yellow)'
  }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {healthy}/{total}
    </span>
  )
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
    <span className="text-[11px] font-medium" style={{ color: config.color }}>
      {config.label}
    </span>
  )
}

export function VMSSTab({ subscriptions, onVMSSClick }: VMSSTabProps) {
  const { instance, accounts } = useMsal()
  const [vmssList, setVMSSList] = useState<VMSSRow[]>([])
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

  async function fetchVMSS() {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (subscriptions.length > 0) {
        params.set('subscriptions', subscriptions.join(','))
      }
      if (search) params.set('search', search)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/vmss?${params}`, { headers })
      const data = await res.json()
      setVMSSList(data.vmss ?? [])
    } catch {
      setError('Failed to load scale sets')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchVMSS() }, [subscriptions]) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = vmssList.filter(vmss =>
    !search || vmss.name.toLowerCase().includes(search.toLowerCase())
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
            Virtual Machine Scale Sets
          </span>
          {!loading && (
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
            >
              {filtered.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search scale sets…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-md outline-none"
            style={{
              background: 'var(--bg-canvas)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              width: '200px',
            }}
          />
          <button
            onClick={fetchVMSS}
            disabled={loading}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh VMSS list"
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
          <Scaling className="h-8 w-8 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {'No scale sets found in selected subscriptions'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Name', 'Resource Group', 'SKU', 'Instances', 'Power State', 'Health', 'Alerts'].map(col => (
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
              {filtered.map(vmss => (
                <tr
                  key={vmss.id}
                  className="cursor-pointer transition-colors"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  onClick={() => onVMSSClick?.(vmss.id, vmss.name)}
                >
                  <td className="px-4 py-3 font-mono text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                    {vmss.name}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vmss.resource_group}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {vmss.sku || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <InstanceCountBadge total={vmss.instance_count} healthy={vmss.healthy_instance_count} />
                  </td>
                  <td className="px-4 py-3">
                    <PowerStateBadge state={vmss.power_state} />
                  </td>
                  <td className="px-4 py-3">
                    <HealthBadge state={vmss.health_state} />
                  </td>
                  <td className="px-4 py-3">
                    {vmss.active_alert_count > 0 ? (
                      <span
                        className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {vmss.active_alert_count}
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
