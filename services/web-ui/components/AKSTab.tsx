'use client'

import { useState, useEffect, useCallback } from 'react'
import { Container, RefreshCw } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { AKSCluster } from '@/types/azure-resources'

interface AKSTabProps {
  subscriptions: string[]
  onAKSClick?: (resourceId: string, resourceName: string) => void
}

function K8sVersionBadge({ version, latestAvailable }: { version: string; latestAvailable: string | null }) {
  const isOutdated = latestAvailable !== null
  const color = isOutdated ? 'var(--accent-yellow)' : 'var(--text-muted)'
  const label = isOutdated ? `${version} · ⬆ available` : version
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

function NodeHealthBadge({ ready, total }: { ready: number; total: number }) {
  const notReady = total - ready
  const ratio = total > 0 ? notReady / total : 0
  let color: string
  if (notReady === 0) {
    color = 'var(--accent-green)'
  } else if (ratio > 0.5) {
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
      {ready}/{total}
    </span>
  )
}

function SystemPodBadge({ health }: { health: 'healthy' | 'degraded' | 'unknown' }) {
  const config = {
    healthy: { label: 'Healthy', color: 'var(--accent-green)' },
    degraded: { label: 'Degraded', color: 'var(--accent-yellow)' },
    unknown: { label: 'Unknown', color: 'var(--text-muted)' },
  }[health]
  return (
    <span className="text-[11px] font-medium" style={{ color: config.color }}>
      {config.label}
    </span>
  )
}

function UpgradeBadge({ latestVersion }: { latestVersion: string | null }) {
  if (!latestVersion) return null
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: 'var(--accent-yellow)',
      }}
    >
      ⬆ {latestVersion}
    </span>
  )
}

export function AKSTab({ subscriptions, onAKSClick }: AKSTabProps) {
  const { instance, accounts } = useMsal()
  const [clusters, setClusters] = useState<AKSCluster[]>([])
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

  async function fetchClusters() {
    if (subscriptions.length === 0) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ subscriptions: subscriptions.join(',') })
      if (search) params.set('search', search)
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/proxy/aks?${params}`, { headers })
      const data = await res.json()
      if (!res.ok) {
        setError(data?.error ?? `Failed to load AKS clusters (${res.status})`)
        setClusters([])
      } else if (data?.fetch_error) {
        setError(`AKS query failed: ${data.fetch_error}`)
        setClusters([])
      } else {
        setClusters(data.clusters ?? [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load AKS clusters')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchClusters() }, [subscriptions]) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = clusters.filter(c =>
    !search || c.name.toLowerCase().includes(search.toLowerCase())
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
            AKS Clusters
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
            placeholder="Search clusters…"
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
            onClick={fetchClusters}
            disabled={loading}
            className="p-1.5 rounded cursor-pointer transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            title="Refresh AKS clusters"
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
          <Container className="h-8 w-8 mx-auto mb-3" style={{ color: 'var(--text-muted)' }} />
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {subscriptions.length === 0
              ? 'Select a subscription to view AKS clusters'
              : 'No AKS clusters found in selected subscriptions'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Cluster', 'Resource Group', 'Location', 'K8s Version', 'Nodes', 'System Pods', 'Upgrade', 'Alerts'].map(col => (
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
              {filtered.map(cluster => (
                <tr
                  key={cluster.id}
                  className="cursor-pointer transition-colors"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  onClick={() => onAKSClick?.(cluster.id, cluster.name)}
                >
                  <td className="px-4 py-3 font-mono text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                    {cluster.name}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {cluster.resource_group}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {cluster.location}
                  </td>
                  <td className="px-4 py-3">
                    <K8sVersionBadge version={cluster.kubernetes_version} latestAvailable={cluster.latest_available_version} />
                  </td>
                  <td className="px-4 py-3">
                    <NodeHealthBadge
                      ready={
                        cluster.ready_nodes > 0
                          ? cluster.ready_nodes
                          : cluster.node_pools_ready === cluster.node_pool_count
                            ? cluster.total_nodes
                            : 0
                      }
                      total={cluster.total_nodes}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <SystemPodBadge health={cluster.system_pod_health} />
                  </td>
                  <td className="px-4 py-3">
                    <UpgradeBadge latestVersion={cluster.latest_available_version} />
                  </td>
                  <td className="px-4 py-3">
                    {cluster.active_alert_count > 0 ? (
                      <span
                        className="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                          color: 'var(--accent-red)',
                        }}
                      >
                        {cluster.active_alert_count}
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
