'use client'

import { useEffect, useState, useCallback } from 'react'
import { Network, RefreshCw, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface PeeringFinding {
  id: string
  subscription_id: string
  resource_group: string
  vnet_name: string
  peering_name: string
  peering_state: string
  provisioning_state: string
  remote_vnet_id: string
  allow_gateway_transit: boolean
  use_remote_gateways: boolean
  is_healthy: boolean
  severity: 'critical' | 'high' | 'info'
  scanned_at: string
}

interface PeeringSummary {
  total: number
  healthy: number
  unhealthy: number
  disconnected: number
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000

function StateBadge({ state }: { state: string }) {
  const lower = state.toLowerCase()
  const style: React.CSSProperties =
    lower === 'connected'
      ? {
          background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
          color: 'var(--accent-green)',
          border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
        }
      : lower === 'disconnected'
      ? {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      : {
          background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
          color: 'var(--accent-yellow)',
          border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
        }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase"
      style={style}
    >
      {state}
    </span>
  )
}

function HealthDot({ healthy }: { healthy: boolean }) {
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full"
      style={{ background: healthy ? 'var(--accent-green)' : 'var(--accent-red)' }}
      aria-label={healthy ? 'Healthy' : 'Unhealthy'}
    />
  )
}

function SummaryCard({
  label,
  value,
  accentVar,
}: {
  label: string
  value: number
  accentVar: string
}) {
  return (
    <div
      className="rounded-lg border p-4 flex flex-col gap-1"
      style={{
        background: `color-mix(in srgb, ${accentVar} 8%, var(--bg-canvas))`,
        borderColor: `color-mix(in srgb, ${accentVar} 20%, transparent)`,
      }}
    >
      <span className="text-2xl font-bold" style={{ color: accentVar }}>
        {value}
      </span>
      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

function truncateResourceId(id: string): string {
  const parts = id.split('/')
  const vnetIndex = parts.findIndex((p) => p.toLowerCase() === 'virtualnetworks')
  if (vnetIndex !== -1 && parts[vnetIndex + 1]) {
    return parts[vnetIndex + 1]
  }
  return id.length > 40 ? `…${id.slice(-40)}` : id
}

export default function VNetPeeringTab() {
  const [findings, setFindings] = useState<PeeringFinding[]>([])
  const [summary, setSummary] = useState<PeeringSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [healthFilter, setHealthFilter] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (healthFilter === 'healthy') params.set('is_healthy', 'true')
      if (healthFilter === 'unhealthy') params.set('is_healthy', 'false')
      const qs = params.toString()

      const [peeringsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/network/peerings${qs ? `?${qs}` : ''}`),
        fetch('/api/proxy/network/peerings/summary'),
      ])

      if (!peeringsRes.ok) {
        const d = await peeringsRes.json()
        throw new Error(d?.error ?? `HTTP ${peeringsRes.status}`)
      }
      if (!summaryRes.ok) {
        const d = await summaryRes.json()
        throw new Error(d?.error ?? `HTTP ${summaryRes.status}`)
      }

      const peeringsData = await peeringsRes.json()
      const summaryData = await summaryRes.json()

      setFindings(peeringsData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [healthFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleScan = async () => {
    setScanning(true)
    try {
      const res = await fetch('/api/proxy/network/peerings/scan', { method: 'POST' })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d?.error ?? `HTTP ${res.status}`)
      }
      await fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Network
            size={20}
            style={{ color: 'var(--accent-blue)' }}
            aria-label="VNet peering icon"
          />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            VNet Peering Health
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1"
          >
            <RefreshCw
              size={14}
              aria-label="Refresh"
              className={loading ? 'animate-spin' : ''}
            />
            Refresh
          </Button>
          <Button size="sm" onClick={handleScan} disabled={scanning}>
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {error && (
        <div
          className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            borderColor: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          <AlertTriangle size={14} aria-label="Error" />
          {error}
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <SummaryCard label="Total Peerings" value={summary.total} accentVar="var(--accent-blue)" />
          <SummaryCard label="Healthy" value={summary.healthy} accentVar="var(--accent-green)" />
          <SummaryCard label="Unhealthy" value={summary.unhealthy} accentVar="var(--accent-yellow)" />
          <SummaryCard label="Disconnected" value={summary.disconnected} accentVar="var(--accent-red)" />
        </div>
      )}

      {/* Filter */}
      <div className="flex flex-wrap gap-2">
        <select
          className="rounded border px-2 py-1 text-sm"
          style={{
            background: 'var(--bg-surface)',
            borderColor: 'var(--border)',
            color: 'var(--text-primary)',
          }}
          value={healthFilter}
          onChange={(e) => setHealthFilter(e.target.value)}
        >
          <option value="">All Peerings</option>
          <option value="healthy">Healthy Only</option>
          <option value="unhealthy">Unhealthy Only</option>
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ color: 'var(--text-secondary)' }}>VNet Name</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Peering Name</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>State</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Provisioning</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Remote VNet</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>GW Transit</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Health</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center py-8"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  Loading…
                </TableCell>
              </TableRow>
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center py-8"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  No peering findings. Run a scan to populate data.
                </TableCell>
              </TableRow>
            ) : (
              findings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell
                    className="font-medium text-sm"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {f.vnet_name}
                  </TableCell>
                  <TableCell
                    className="text-sm"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {f.peering_name}
                  </TableCell>
                  <TableCell>
                    <StateBadge state={f.peering_state} />
                  </TableCell>
                  <TableCell
                    className="text-sm"
                    style={{
                      color:
                        f.provisioning_state.toLowerCase() === 'succeeded'
                          ? 'var(--text-secondary)'
                          : 'var(--accent-yellow)',
                    }}
                  >
                    {f.provisioning_state}
                  </TableCell>
                  <TableCell
                    className="font-mono text-xs max-w-[180px] truncate"
                    style={{ color: 'var(--text-secondary)' }}
                    title={f.remote_vnet_id}
                  >
                    {truncateResourceId(f.remote_vnet_id)}
                  </TableCell>
                  <TableCell
                    className="text-xs text-center"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {f.allow_gateway_transit ? (
                      <span style={{ color: 'var(--accent-green)' }}>Yes</span>
                    ) : (
                      '—'
                    )}
                  </TableCell>
                  <TableCell>
                    <HealthDot healthy={f.is_healthy} />
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
