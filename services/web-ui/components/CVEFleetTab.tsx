'use client'

import { useState, useEffect, useCallback } from 'react'
import { ShieldAlert, RefreshCw, AlertTriangle, ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// ── Types ─────────────────────────────────────────────────────────────────────

interface CVEFleetRow {
  readonly vm_name: string
  readonly subscription_id: string
  readonly resource_group: string
  readonly os_type: string
  readonly os_version: string
  readonly vm_type: string
  readonly critical_count: number | null
  readonly high_count: number | null
  readonly medium_count: number | null
  readonly low_count: number | null
  readonly total_unpatched: number | null
  readonly top_cves: readonly string[]
  readonly patch_status: 'CRITICAL' | 'HIGH' | 'MEDIUM_LOW' | 'CLEAN' | 'NO_DATA' | 'UNKNOWN'
  readonly has_data: boolean
}

interface CVEFleetResponse {
  readonly vms: CVEFleetRow[]
  readonly total_vms: number
  readonly vms_with_data: number
  readonly query_time_ms: number
}

interface CVEFleetTabProps {
  subscriptions: string[]
  onViewDetails?: (vmName: string, subscriptionId: string, resourceGroup: string) => void
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000 // 10 minutes

// ── Severity helpers ──────────────────────────────────────────────────────────

function patchStatusColor(status: string): string {
  switch (status) {
    case 'CRITICAL':   return 'var(--accent-red)'
    case 'HIGH':       return 'var(--accent-orange)'
    case 'MEDIUM_LOW': return 'var(--accent-yellow)'
    case 'CLEAN':      return 'var(--accent-green)'
    default:           return 'var(--text-muted)'
  }
}

function patchStatusLabel(status: string): string {
  switch (status) {
    case 'CRITICAL':   return 'Critical CVEs'
    case 'HIGH':       return 'High CVEs'
    case 'MEDIUM_LOW': return 'Medium/Low'
    case 'CLEAN':      return 'Clean'
    case 'NO_DATA':    return 'No Data'
    default:           return status
  }
}

function rowHeatmapStyle(status: string): React.CSSProperties {
  if (status === 'NO_DATA' || status === 'UNKNOWN') return {}
  const color = patchStatusColor(status)
  return {
    borderLeft: `3px solid ${color}`,
  }
}

function PatchStatusBadge({ status }: { status: string }) {
  const color = patchStatusColor(status)
  return (
    <Badge
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 40%, transparent)`,
      }}
    >
      {patchStatusLabel(status)}
    </Badge>
  )
}

function CountCell({ value, color }: { value: number | null; color: string }) {
  if (value === null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  if (value === 0) return <span style={{ color: 'var(--text-muted)' }}>0</span>
  return (
    <span
      className="font-semibold tabular-nums"
      style={{ color }}
    >
      {value}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CVEFleetTab({ subscriptions, onViewDetails }: CVEFleetTabProps) {
  const [rows, setRows] = useState<CVEFleetRow[]>([])
  const [totalVms, setTotalVms] = useState(0)
  const [vmsWithData, setVmsWithData] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [osFilter, setOsFilter] = useState<string>('ALL')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Backend expects comma-separated subscriptions (Optional[str])
      const subParam = subscriptions.length > 0
        ? `?subscriptions=${encodeURIComponent(subscriptions.join(','))}`
        : ''

      const res = await fetch(`/api/proxy/cve/fleet${subParam}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.error ?? `HTTP ${res.status}`)
      }
      const data: CVEFleetResponse = await res.json()
      setRows(data.vms ?? [])
      setTotalVms(data.total_vms ?? 0)
      setVmsWithData(data.vms_with_data ?? 0)
      setLastUpdated(new Date())
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [subscriptions])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  // ── Filtering ──────────────────────────────────────────────────────────────

  const filteredRows = rows.filter(row => {
    if (statusFilter !== 'ALL' && row.patch_status !== statusFilter) return false
    if (osFilter !== 'ALL' && row.os_type.toLowerCase() !== osFilter.toLowerCase()) return false
    return true
  })

  const osTypes = Array.from(new Set(rows.map(r => r.os_type).filter(Boolean)))

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <ShieldAlert size={18} style={{ color: 'var(--accent-red)' }} />
          <span className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>
            CVE Exposure
          </span>
          {!loading && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {totalVms} VMs · {vmsWithData} with CVE data
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Status filter */}
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All statuses</SelectItem>
              <SelectItem value="CRITICAL">Critical</SelectItem>
              <SelectItem value="HIGH">High</SelectItem>
              <SelectItem value="MEDIUM_LOW">Medium / Low</SelectItem>
              <SelectItem value="CLEAN">Clean</SelectItem>
              <SelectItem value="NO_DATA">No Data</SelectItem>
            </SelectContent>
          </Select>
          {/* OS filter */}
          {osTypes.length > 1 && (
            <Select value={osFilter} onValueChange={setOsFilter}>
              <SelectTrigger className="h-8 w-28 text-xs">
                <SelectValue placeholder="All OS" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All OS</SelectItem>
                {osTypes.map(os => (
                  <SelectItem key={os} value={os}>{os}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {lastUpdated && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          {loading && (
            <RefreshCw
              size={14}
              className="animate-spin"
              style={{ color: 'var(--text-muted)' }}
            />
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div
          className="flex items-center gap-2 rounded-md p-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            color: 'var(--accent-red)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
          }}
        >
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)' }}
      >
        <Table>
          <TableHeader>
            <TableRow style={{ background: 'var(--bg-surface)' }}>
              <TableHead className="text-xs font-semibold">VM Name</TableHead>
              <TableHead className="text-xs font-semibold">Subscription</TableHead>
              <TableHead className="text-xs font-semibold">OS</TableHead>
              <TableHead className="text-xs font-semibold text-center">
                <span style={{ color: 'var(--accent-red)' }}>Critical</span>
              </TableHead>
              <TableHead className="text-xs font-semibold text-center">
                <span style={{ color: 'var(--accent-orange)' }}>High</span>
              </TableHead>
              <TableHead className="text-xs font-semibold">Top CVEs</TableHead>
              <TableHead className="text-xs font-semibold">Status</TableHead>
              <TableHead className="text-xs font-semibold">Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredRows.length === 0 && !loading && (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="text-center py-10 text-sm"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {rows.length === 0 ? 'No CVE data found' : 'No VMs match the current filters'}
                </TableCell>
              </TableRow>
            )}
            {filteredRows.map(row => (
              <TableRow
                key={`${row.subscription_id}/${row.resource_group}/${row.vm_name}`}
                style={{
                  ...rowHeatmapStyle(row.patch_status),
                  background: 'var(--bg-canvas)',
                }}
                className="hover:brightness-95 transition-all"
              >
                <TableCell className="text-xs font-medium">
                  <div style={{ color: 'var(--text-primary)' }}>{row.vm_name}</div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                    {row.vm_type} · {row.resource_group}
                  </div>
                </TableCell>
                <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  <span className="font-mono text-[10px]">
                    {row.subscription_id.slice(0, 8)}…
                  </span>
                </TableCell>
                <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {row.os_version || row.os_type || '—'}
                </TableCell>
                <TableCell className="text-center">
                  <CountCell value={row.critical_count} color="var(--accent-red)" />
                </TableCell>
                <TableCell className="text-center">
                  <CountCell value={row.high_count} color="var(--accent-orange)" />
                </TableCell>
                <TableCell className="text-xs">
                  {row.top_cves.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {row.top_cves.map(cve => (
                        <span
                          key={cve}
                          className="font-mono text-[10px] px-1.5 py-0.5 rounded"
                          style={{
                            background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                            color: 'var(--accent-blue)',
                          }}
                        >
                          {cve}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>—</span>
                  )}
                </TableCell>
                <TableCell>
                  <PatchStatusBadge status={row.patch_status} />
                </TableCell>
                <TableCell>
                  {onViewDetails ? (
                    <button
                      onClick={() => onViewDetails(row.vm_name, row.subscription_id, row.resource_group)}
                      className="flex items-center gap-1 text-xs transition-colors hover:underline"
                      style={{ color: 'var(--accent-blue)' }}
                    >
                      View <ExternalLink size={10} />
                    </button>
                  ) : (
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
