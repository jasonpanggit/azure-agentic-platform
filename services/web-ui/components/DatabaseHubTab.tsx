'use client'

import { useState, useEffect, useCallback } from 'react'
import { Database, Activity, Gauge, CheckCircle, AlertCircle, Circle } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface DatabaseRecord {
  resource_id: string
  name: string
  db_type: 'cosmos' | 'postgresql' | 'sql'
  resource_group: string
  subscription_id: string
  location: string
  state: string
  health_status: 'healthy' | 'stopped' | 'failed' | 'provisioning'
  sku_name: string
  version: string
  findings: string[]
  scanned_at: string
}

interface HealthResponse {
  databases: DatabaseRecord[]
  total: number
  error?: string
}

interface SlowQueryServer {
  resource_id: string
  name: string
  db_type: 'postgresql' | 'sql'
  resource_group: string
  subscription_id: string
  location: string
  health_status: string
  state: string
}

interface ThroughputResource {
  resource_id: string
  name: string
  db_type: 'cosmos' | 'sql'
  resource_group: string
  subscription_id: string
  location: string
  health_status: string
  sku_name: string
}

// ─── Constants ────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 10 * 60 * 1000 // 10 minutes

const subTabs = [
  { id: 'health',       label: 'Health Overview', icon: Database },
  { id: 'slow-queries', label: 'Slow Queries',    icon: Activity },
  { id: 'throughput',   label: 'Throughput',      icon: Gauge    },
]

const DB_TYPE_LABELS: Record<string, string> = {
  cosmos:     'Cosmos DB',
  postgresql: 'PostgreSQL',
  sql:        'Azure SQL',
}

// ─── Status helpers ───────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  if (status === 'healthy') {
    return <CheckCircle className="w-4 h-4" style={{ color: 'var(--accent-green)' }} />
  }
  if (status === 'failed') {
    return <AlertCircle className="w-4 h-4" style={{ color: 'var(--accent-red)' }} />
  }
  if (status === 'stopped') {
    return <Circle className="w-4 h-4" style={{ color: 'var(--accent-yellow)' }} />
  }
  return <Circle className="w-4 h-4" style={{ color: 'var(--text-secondary)' }} />
}

function DbTypeBadge({ dbType }: { dbType: string }) {
  const colorMap: Record<string, string> = {
    cosmos:     'var(--accent-blue)',
    postgresql: 'var(--accent-purple)',
    sql:        'var(--accent-teal)',
  }
  const color = colorMap[dbType] ?? 'var(--accent-blue)'
  return (
    <span
      className="px-2 py-0.5 rounded text-xs font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {DB_TYPE_LABELS[dbType] ?? dbType}
    </span>
  )
}

// ─── Health Overview sub-tab ──────────────────────────────────────────────────

function HealthOverviewTab({ subscriptions }: { subscriptions: string[] }) {
  const [databases, setDatabases] = useState<DatabaseRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dbTypeFilter, setDbTypeFilter] = useState<string>('')

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (subscriptions.length === 1) params.set('subscription_id', subscriptions[0])
      if (dbTypeFilter) params.set('db_type', dbTypeFilter)
      const res = await fetch(`/api/proxy/database/health?${params}`)
      const data: HealthResponse = await res.json()
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      setDatabases(data.databases ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load database health')
    } finally {
      setLoading(false)
    }
  }, [subscriptions, dbTypeFilter])

  useEffect(() => {
    setLoading(true)
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12" style={{ color: 'var(--text-secondary)' }}>
        <span className="text-sm">Loading database health…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg p-4" style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', border: '1px solid var(--accent-red)' }}>
        <p className="text-sm" style={{ color: 'var(--accent-red)' }}>{error}</p>
      </div>
    )
  }

  const healthy = databases.filter(d => d.health_status === 'healthy').length
  const failed  = databases.filter(d => d.health_status === 'failed').length
  const stopped = databases.filter(d => d.health_status === 'stopped').length

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Total',   value: databases.length, color: 'var(--accent-blue)'   },
          { label: 'Healthy', value: healthy,           color: 'var(--accent-green)'  },
          { label: 'Stopped', value: stopped,           color: 'var(--accent-yellow)' },
          { label: 'Failed',  value: failed,            color: 'var(--accent-red)'    },
        ].map(card => (
          <div
            key={card.label}
            className="rounded-lg p-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <p className="text-xs mb-1" style={{ color: 'var(--text-secondary)' }}>{card.label}</p>
            <p className="text-2xl font-semibold" style={{ color: card.color }}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* Type filter pills */}
      <div className="flex gap-2">
        {['', 'cosmos', 'postgresql', 'sql'].map(type => (
          <button
            key={type}
            onClick={() => setDbTypeFilter(type)}
            className="px-3 py-1 rounded text-xs font-medium transition-all"
            style={
              dbTypeFilter === type
                ? { background: 'var(--accent-blue)', color: '#fff' }
                : { background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }
            }
          >
            {type ? DB_TYPE_LABELS[type] : 'All'}
          </button>
        ))}
      </div>

      {/* Table */}
      {databases.length === 0 ? (
        <p className="text-sm py-8 text-center" style={{ color: 'var(--text-secondary)' }}>
          No database resources found
        </p>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Status</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Name</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Type</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Resource Group</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Location</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>State</th>
              </tr>
            </thead>
            <tbody>
              {databases.map((db, i) => (
                <tr
                  key={db.resource_id}
                  style={{
                    background: i % 2 === 0 ? 'var(--bg-canvas)' : 'var(--bg-surface)',
                    borderBottom: '1px solid var(--border)',
                  }}
                >
                  <td className="px-4 py-2">
                    <StatusDot status={db.health_status} />
                  </td>
                  <td className="px-4 py-2 font-medium" style={{ color: 'var(--text-primary)' }}>{db.name}</td>
                  <td className="px-4 py-2"><DbTypeBadge dbType={db.db_type} /></td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{db.resource_group}</td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{db.location}</td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{db.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Slow Queries sub-tab ─────────────────────────────────────────────────────

function SlowQueriesTab({ subscriptions }: { subscriptions: string[] }) {
  const [servers, setServers] = useState<SlowQueryServer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (subscriptions.length === 1) params.set('subscription_id', subscriptions[0])
      const res = await fetch(`/api/proxy/database/slow-queries?${params}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      setServers(data.servers ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load slow query data')
    } finally {
      setLoading(false)
    }
  }, [subscriptions])

  useEffect(() => {
    setLoading(true)
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  if (loading) {
    return <div className="flex items-center justify-center py-12" style={{ color: 'var(--text-secondary)' }}><span className="text-sm">Loading slow query data…</span></div>
  }
  if (error) {
    return <div className="rounded-lg p-4" style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', border: '1px solid var(--accent-red)' }}><p className="text-sm" style={{ color: 'var(--accent-red)' }}>{error}</p></div>
  }

  return (
    <div className="space-y-4">
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        Shows PostgreSQL and Azure SQL servers. Use the chat panel to query slow logs per server
        via the Database agent (requires Log Analytics workspace configured on the server).
      </p>
      {servers.length === 0 ? (
        <p className="text-sm py-8 text-center" style={{ color: 'var(--text-secondary)' }}>No PostgreSQL or SQL servers found</p>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Status</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Server</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Type</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Resource Group</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Location</th>
              </tr>
            </thead>
            <tbody>
              {servers.map((s, i) => (
                <tr key={s.resource_id} style={{ background: i % 2 === 0 ? 'var(--bg-canvas)' : 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
                  <td className="px-4 py-2"><StatusDot status={s.health_status} /></td>
                  <td className="px-4 py-2 font-medium" style={{ color: 'var(--text-primary)' }}>{s.name}</td>
                  <td className="px-4 py-2"><DbTypeBadge dbType={s.db_type} /></td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{s.resource_group}</td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{s.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Throughput sub-tab ───────────────────────────────────────────────────────

function ThroughputTab({ subscriptions }: { subscriptions: string[] }) {
  const [resources, setResources] = useState<ThroughputResource[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (subscriptions.length === 1) params.set('subscription_id', subscriptions[0])
      const res = await fetch(`/api/proxy/database/throughput?${params}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      setResources(data.resources ?? [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load throughput data')
    } finally {
      setLoading(false)
    }
  }, [subscriptions])

  useEffect(() => {
    setLoading(true)
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  if (loading) {
    return <div className="flex items-center justify-center py-12" style={{ color: 'var(--text-secondary)' }}><span className="text-sm">Loading throughput data…</span></div>
  }
  if (error) {
    return <div className="rounded-lg p-4" style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', border: '1px solid var(--accent-red)' }}><p className="text-sm" style={{ color: 'var(--accent-red)' }}>{error}</p></div>
  }

  return (
    <div className="space-y-4">
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        Shows Cosmos DB and Azure SQL resources. Use the chat panel to query RU/DTU utilisation metrics
        via the Database agent.
      </p>
      {resources.length === 0 ? (
        <p className="text-sm py-8 text-center" style={{ color: 'var(--text-secondary)' }}>No Cosmos DB or SQL resources found</p>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Status</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Resource</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Type</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>SKU</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Resource Group</th>
                <th className="text-left px-4 py-2 font-medium" style={{ color: 'var(--text-secondary)' }}>Location</th>
              </tr>
            </thead>
            <tbody>
              {resources.map((r, i) => (
                <tr key={r.resource_id} style={{ background: i % 2 === 0 ? 'var(--bg-canvas)' : 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
                  <td className="px-4 py-2"><StatusDot status={r.health_status} /></td>
                  <td className="px-4 py-2 font-medium" style={{ color: 'var(--text-primary)' }}>{r.name}</td>
                  <td className="px-4 py-2"><DbTypeBadge dbType={r.db_type} /></td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{r.sku_name || '—'}</td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{r.resource_group}</td>
                  <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{r.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Hub tab shell ────────────────────────────────────────────────────────────

interface DatabaseHubTabProps {
  subscriptions: string[]
  initialSubTab?: string
}

export function DatabaseHubTab({
  subscriptions,
  initialSubTab = 'health',
}: DatabaseHubTabProps) {
  const [activeSubTab, setActiveSubTab] = useState(initialSubTab)

  return (
    <div>
      {/* Sub-tab navigation */}
      <div
        className="flex gap-1 mb-6 p-1 rounded-lg"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        {subTabs.map(tab => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              onClick={() => setActiveSubTab(tab.id)}
              className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all"
              style={
                activeSubTab === tab.id
                  ? { background: 'var(--accent-blue)', color: '#ffffff' }
                  : { color: 'var(--text-secondary)' }
              }
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Sub-tab content */}
      {activeSubTab === 'health'       && <HealthOverviewTab subscriptions={subscriptions} />}
      {activeSubTab === 'slow-queries' && <SlowQueriesTab   subscriptions={subscriptions} />}
      {activeSubTab === 'throughput'   && <ThroughputTab    subscriptions={subscriptions} />}
    </div>
  )
}
