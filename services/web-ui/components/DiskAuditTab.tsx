'use client'

import { useEffect, useState, useCallback } from 'react'
import { HardDrive, AlertTriangle } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface DiskFinding {
  id: string
  subscription_id: string
  resource_group: string
  resource_name: string
  resource_type: 'disk' | 'snapshot'
  size_gb: number
  sku: string
  days_old: number
  created_at: string
  estimated_monthly_cost_usd: number
  severity: 'high' | 'medium' | 'low'
  scanned_at: string
}

interface DiskSummary {
  orphaned_disks: number
  old_snapshots: number
  total_wasted_gb: number
  estimated_monthly_cost_usd: number
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000

function TypeBadge({ type }: { type: 'disk' | 'snapshot' }) {
  const style: React.CSSProperties =
    type === 'disk'
      ? {
          background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
          color: 'var(--accent-blue)',
          border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
        }
      : {
          background: 'color-mix(in srgb, var(--accent-purple, var(--accent-blue)) 15%, transparent)',
          color: 'var(--accent-purple, var(--accent-blue))',
          border: '1px solid color-mix(in srgb, var(--accent-purple, var(--accent-blue)) 30%, transparent)',
        }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase"
      style={style}
    >
      {type}
    </span>
  )
}

function SeverityBadge({ severity }: { severity: string }) {
  const style: React.CSSProperties =
    severity === 'high'
      ? {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      : severity === 'medium'
      ? {
          background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
          color: 'var(--accent-yellow)',
          border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
        }
      : {
          background: 'color-mix(in srgb, var(--text-secondary) 15%, transparent)',
          color: 'var(--text-secondary)',
          border: '1px solid color-mix(in srgb, var(--text-secondary) 30%, transparent)',
        }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase"
      style={style}
    >
      {severity}
    </span>
  )
}

function SummaryCard({
  label,
  value,
  accentVar,
  format,
}: {
  label: string
  value: number
  accentVar: string
  format?: 'number' | 'gb' | 'usd'
}) {
  const display =
    format === 'usd'
      ? value >= 1000
        ? `$${(value / 1000).toFixed(1)}K`
        : `$${value.toFixed(2)}`
      : format === 'gb'
      ? `${value.toLocaleString()} GB`
      : value.toString()

  return (
    <div
      className="rounded-lg border p-4 flex flex-col gap-1"
      style={{
        background: `color-mix(in srgb, ${accentVar} 8%, var(--bg-canvas))`,
        borderColor: `color-mix(in srgb, ${accentVar} 20%, transparent)`,
      }}
    >
      <span className="text-2xl font-bold" style={{ color: accentVar }}>
        {display}
      </span>
      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

function formatCost(value: number): string {
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`
  return `$${value.toFixed(2)}`
}

export default function DiskAuditTab() {
  const [findings, setFindings] = useState<DiskFinding[]>([])
  const [summary, setSummary] = useState<DiskSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (typeFilter) params.set('resource_type', typeFilter)
      const qs = params.toString()

      const [disksRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/compute/disks${qs ? `?${qs}` : ''}`),
        fetch('/api/proxy/compute/disks/summary'),
      ])

      if (!disksRes.ok) {
        const d = await disksRes.json()
        throw new Error(d?.error ?? `HTTP ${disksRes.status}`)
      }
      if (!summaryRes.ok) {
        const d = await summaryRes.json()
        throw new Error(d?.error ?? `HTTP ${summaryRes.status}`)
      }

      const disksData = await disksRes.json()
      const summaryData = await summaryRes.json()

      setFindings(disksData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [typeFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <HardDrive
          size={20}
          style={{ color: 'var(--accent-yellow)' }}
          aria-label="Disk audit icon"
        />
        <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
          Orphaned Disk & Snapshot Audit
        </h2>
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
          <SummaryCard
            label="Orphaned Disks"
            value={summary.orphaned_disks}
            accentVar="var(--accent-red)"
          />
          <SummaryCard
            label="Old Snapshots"
            value={summary.old_snapshots}
            accentVar="var(--accent-yellow)"
          />
          <SummaryCard
            label="Total Wasted Storage"
            value={summary.total_wasted_gb}
            accentVar="var(--accent-blue)"
            format="gb"
          />
          <SummaryCard
            label="Est. Monthly Waste"
            value={summary.estimated_monthly_cost_usd}
            accentVar="var(--accent-orange, var(--accent-yellow))"
            format="usd"
          />
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
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">All Types</option>
          <option value="disk">Disks Only</option>
          <option value="snapshot">Snapshots Only</option>
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Resource Name</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Type</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Size (GB)</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>SKU / Age</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Est. Monthly Cost</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Severity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center py-8"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  Loading…
                </TableCell>
              </TableRow>
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center py-8"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  No orphaned disks or old snapshots found.
                </TableCell>
              </TableRow>
            ) : (
              findings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell
                    className="font-medium text-sm"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {f.resource_name}
                  </TableCell>
                  <TableCell>
                    <TypeBadge type={f.resource_type} />
                  </TableCell>
                  <TableCell
                    className="text-sm tabular-nums"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {f.size_gb.toLocaleString()}
                  </TableCell>
                  <TableCell
                    className="text-sm"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {f.resource_type === 'disk' ? (
                      f.sku || '—'
                    ) : (
                      <span>
                        {f.days_old}
                        <span style={{ color: 'var(--text-secondary)' }}> days</span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell
                    className="text-sm tabular-nums font-medium"
                    style={{ color: 'var(--accent-yellow)' }}
                  >
                    {formatCost(f.estimated_monthly_cost_usd)}
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={f.severity} />
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
