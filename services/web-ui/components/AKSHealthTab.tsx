'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { RefreshCw, ChevronDown, ChevronRight, Lock, Unlock, ShieldCheck, ShieldOff } from 'lucide-react'

interface NodePool {
  name: string
  count: number
  vm_size: string
  mode: string
  autoscaling: boolean
  state: string
  os_type: string
  min_count?: number | null
  max_count?: number | null
  provisioning_state: string
}

interface AKSCluster {
  cluster_id: string
  arm_id: string
  cluster_name: string
  resource_group: string
  subscription_id: string
  location: string
  kubernetes_version: string
  power_state: string
  provisioning_state: string
  node_count: number
  node_pools: NodePool[]
  private_cluster: boolean
  enable_rbac: boolean
  fqdn: string
  health_status: 'healthy' | 'degraded' | 'stopped' | 'provisioning'
  health_reasons: string[]
  scanned_at: string
}

interface AKSSummary {
  total_clusters: number
  healthy: number
  degraded: number
  stopped: number
  total_nodes: number
  clusters_without_rbac: number
  clusters_without_private_api: number
  outdated_version_count: number
}

interface AKSHealthTabProps {
  subscriptions?: string[]
}

const HEALTH_COLORS: Record<string, string> = {
  healthy: 'var(--accent-green)',
  degraded: 'var(--accent-red)',
  stopped: 'var(--text-secondary)',
  provisioning: 'var(--accent-yellow)',
}

const HEALTH_BG: Record<string, string> = {
  healthy: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
  degraded: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
  stopped: 'color-mix(in srgb, var(--text-secondary) 15%, transparent)',
  provisioning: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
}

function HealthBadge({ status }: { status: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        color: HEALTH_COLORS[status] ?? 'var(--text-primary)',
        background: HEALTH_BG[status] ?? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
      }}
    >
      {status}
    </span>
  )
}

function SummaryStrip({ summary, loading }: { summary: AKSSummary | null; loading: boolean }) {
  const items = [
    { label: 'Total', value: summary?.total_clusters ?? 0, color: 'var(--text-primary)' },
    { label: 'Healthy', value: summary?.healthy ?? 0, color: 'var(--accent-green)' },
    { label: 'Degraded', value: summary?.degraded ?? 0, color: 'var(--accent-red)' },
    { label: 'Stopped', value: summary?.stopped ?? 0, color: 'var(--text-secondary)' },
    { label: 'Total Nodes', value: summary?.total_nodes ?? 0, color: 'var(--accent-blue)' },
  ]

  return (
    <div className="grid grid-cols-5 gap-3 mb-6">
      {items.map(({ label, value, color }) => (
        <Card key={label} style={{ border: '1px solid var(--border)' }}>
          <CardContent className="p-4">
            {loading ? (
              <Skeleton className="h-8 w-full" />
            ) : (
              <>
                <div className="text-2xl font-bold" style={{ color }}>{value}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{label}</div>
              </>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function NodePoolTable({ pools }: { pools: NodePool[] }) {
  return (
    <div className="mt-3 ml-4 rounded overflow-hidden" style={{ border: '1px solid var(--border)' }}>
      <Table>
        <TableHeader>
          <TableRow style={{ background: 'var(--bg-subtle)' }}>
            <TableHead className="text-xs">Pool Name</TableHead>
            <TableHead className="text-xs">VM Size</TableHead>
            <TableHead className="text-xs">Count</TableHead>
            <TableHead className="text-xs">Mode</TableHead>
            <TableHead className="text-xs">Autoscaling</TableHead>
            <TableHead className="text-xs">State</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pools.map((pool) => (
            <TableRow key={pool.name}>
              <TableCell className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>{pool.name}</TableCell>
              <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>{pool.vm_size}</TableCell>
              <TableCell className="text-xs">
                {pool.autoscaling
                  ? `${pool.count} (${pool.min_count ?? '?'}–${pool.max_count ?? '?'})`
                  : pool.count}
              </TableCell>
              <TableCell className="text-xs">{pool.mode}</TableCell>
              <TableCell className="text-xs">
                {pool.autoscaling
                  ? <span style={{ color: 'var(--accent-green)' }}>On</span>
                  : <span style={{ color: 'var(--text-secondary)' }}>Off</span>}
              </TableCell>
              <TableCell className="text-xs">
                <span style={{
                  color: pool.provisioning_state === 'Succeeded' ? 'var(--accent-green)' : 'var(--accent-yellow)',
                }}>
                  {pool.provisioning_state}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ClusterCard({ cluster }: { cluster: AKSCluster }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-md"
      style={{ border: '1px solid var(--border)' }}
      onClick={() => setExpanded((e) => !e)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            {expanded
              ? <ChevronDown className="h-4 w-4 shrink-0" style={{ color: 'var(--text-secondary)' }} />
              : <ChevronRight className="h-4 w-4 shrink-0" style={{ color: 'var(--text-secondary)' }} />}
            <div>
              <div className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>
                {cluster.cluster_name}
              </div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                {cluster.resource_group} · {cluster.location}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* K8s version badge */}
            <span
              className="text-xs px-2 py-0.5 rounded font-mono"
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
                color: 'var(--accent-blue)',
              }}
            >
              k8s {cluster.kubernetes_version}
            </span>

            {/* RBAC indicator */}
            {cluster.enable_rbac
              ? <ShieldCheck className="h-4 w-4" style={{ color: 'var(--accent-green)' }} aria-label="RBAC enabled" />
              : <ShieldOff className="h-4 w-4" style={{ color: 'var(--accent-red)' }} aria-label="RBAC disabled" />}

            {/* Private cluster indicator */}
            {cluster.private_cluster
              ? <Lock className="h-4 w-4" style={{ color: 'var(--accent-green)' }} aria-label="Private API server" />
              : <Unlock className="h-4 w-4" style={{ color: 'var(--accent-yellow)' }} aria-label="Public API server" />}

            {/* Node count */}
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {cluster.node_count} nodes
            </span>

            <HealthBadge status={cluster.health_status} />
          </div>
        </div>

        {/* Health reasons */}
        {cluster.health_reasons.length > 0 && (
          <div className="mt-2 ml-6">
            {cluster.health_reasons.map((reason) => (
              <div key={reason} className="text-xs" style={{ color: 'var(--accent-red)' }}>
                • {reason}
              </div>
            ))}
          </div>
        )}

        {/* Expanded node pool table */}
        {expanded && cluster.node_pools.length > 0 && (
          <NodePoolTable pools={cluster.node_pools} />
        )}

        {expanded && cluster.node_pools.length === 0 && (
          <div className="ml-6 mt-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
            No node pool data available. Run a scan to refresh.
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function AKSHealthTab({ subscriptions = [] }: AKSHealthTabProps) {
  const [clusters, setClusters] = useState<AKSCluster[]>([])
  const [summary, setSummary] = useState<AKSSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [filterSub, setFilterSub] = useState<string>('all')
  const [filterHealth, setFilterHealth] = useState<string>('all')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const subParam = filterSub !== 'all' ? `?subscription_id=${filterSub}` : ''
      const healthParam = filterHealth !== 'all'
        ? (subParam ? `&health_status=${filterHealth}` : `?health_status=${filterHealth}`)
        : ''
      const [clustersRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/aks-health/clusters${subParam}${healthParam}`),
        fetch('/api/proxy/aks-health/summary'),
      ])
      if (clustersRes.ok) {
        const data = await clustersRes.json()
        setClusters(data.clusters ?? [])
      }
      if (summaryRes.ok) {
        const data = await summaryRes.json()
        setSummary(data)
      }
    } catch {
      // silent — UI shows empty state
    } finally {
      setLoading(false)
    }
  }, [filterSub, filterHealth])

  useEffect(() => {
    void fetchData()
    const interval = setInterval(() => { void fetchData() }, 10 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      await fetch('/api/proxy/aks-health/scan', { method: 'POST' })
      // Wait a moment then refresh
      setTimeout(() => { void fetchData() }, 3000)
    } finally {
      setTimeout(() => setScanning(false), 3000)
    }
  }

  const uniqueSubs = Array.from(new Set(clusters.map((c) => c.subscription_id)))

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            AKS Cluster Health
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            Click a cluster to expand node pool details
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchData()}
            disabled={loading}
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={() => void handleScan()}
            disabled={scanning}
            style={{ background: 'var(--accent-blue)', color: '#fff' }}
          >
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {/* Summary strip */}
      <SummaryStrip summary={summary} loading={loading} />

      {/* Filters */}
      <div className="flex items-center gap-3">
        <Select value={filterSub} onValueChange={setFilterSub}>
          <SelectTrigger className="w-48 text-sm" style={{ borderColor: 'var(--border)' }}>
            <SelectValue placeholder="All subscriptions" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All subscriptions</SelectItem>
            {uniqueSubs.map((s) => (
              <SelectItem key={s} value={s}>{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filterHealth} onValueChange={setFilterHealth}>
          <SelectTrigger className="w-44 text-sm" style={{ borderColor: 'var(--border)' }}>
            <SelectValue placeholder="All health states" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All states</SelectItem>
            <SelectItem value="healthy">Healthy</SelectItem>
            <SelectItem value="degraded">Degraded</SelectItem>
            <SelectItem value="stopped">Stopped</SelectItem>
            <SelectItem value="provisioning">Provisioning</SelectItem>
          </SelectContent>
        </Select>

        <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          {clusters.length} cluster{clusters.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Cluster grid */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      ) : clusters.length === 0 ? (
        <div
          className="rounded-lg p-8 text-center text-sm"
          style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
        >
          No AKS clusters found. Run a scan to populate data.
        </div>
      ) : (
        <div className="space-y-3">
          {clusters.map((cluster) => (
            <ClusterCard key={cluster.cluster_id} cluster={cluster} />
          ))}
        </div>
      )}
    </div>
  )
}
