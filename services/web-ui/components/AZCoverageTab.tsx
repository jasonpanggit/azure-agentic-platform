'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface AZFinding {
  id: string
  subscription_id: string
  resource_group: string
  resource_name: string
  resource_type: string
  location: string
  zones: string[]
  has_zone_redundancy: boolean
  zone_count: number
  severity: string
  recommendation: string
  scanned_at: string
}

interface AZSummary {
  total: number
  zone_redundant: number
  non_redundant: number
  coverage_pct: number
}

function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase()
  const style: React.CSSProperties =
    s === 'high'
      ? { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)', border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)' }
      : { background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)', color: 'var(--accent-blue)', border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)' }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase" style={style}>
      {severity}
    </span>
  )
}

function ResourceTypeBadge({ resourceType }: { resourceType: string }) {
  const isVmss = resourceType === 'vmss'
  const style: React.CSSProperties = isVmss
    ? { background: 'color-mix(in srgb, var(--accent-purple) 15%, transparent)', color: 'var(--accent-purple)', border: '1px solid color-mix(in srgb, var(--accent-purple) 30%, transparent)' }
    : { background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)', color: 'var(--accent-blue)', border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)' }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium uppercase" style={style}>
      {resourceType.toUpperCase()}
    </span>
  )
}

function HaBadge({ redundant }: { redundant: boolean }) {
  const style: React.CSSProperties = redundant
    ? { background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)', color: 'var(--accent-green)', border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)' }
    : { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)', border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)' }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium" style={style}>
      {redundant ? 'Zone-Redundant' : 'Non-Redundant'}
    </span>
  )
}

function ZonePills({ zones }: { zones: string[] }) {
  if (zones.length === 0) {
    return <span style={{ color: 'var(--text-muted)' }} className="text-[12px]">None</span>
  }
  return (
    <div className="flex gap-1 flex-wrap">
      {zones.map((z) => (
        <span
          key={z}
          className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium"
          style={{ background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)', color: 'var(--accent-blue)', border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)' }}
        >
          Z{z}
        </span>
      ))}
    </div>
  )
}

function StatCard({ label, value, suffix, color }: { label: string; value: number | string; suffix?: string; color?: string }) {
  return (
    <div
      className="rounded-lg px-4 py-3 flex flex-col gap-0.5 min-w-[120px]"
      style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
    >
      <span className="text-[22px] font-bold" style={{ color: color ?? 'var(--text-primary)' }}>
        {value}{suffix}
      </span>
      <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

function CoverageBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? 'var(--accent-green)' : pct >= 50 ? 'var(--accent-yellow)' : 'var(--accent-red)'
  return (
    <div className="flex items-center gap-2">
      <div
        className="rounded-full overflow-hidden"
        style={{ width: 120, height: 8, background: 'var(--border)' }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(pct, 100)}%`, background: color }}
        />
      </div>
      <span className="text-[13px] font-semibold" style={{ color }}>
        {pct.toFixed(1)}%
      </span>
    </div>
  )
}

export function AZCoverageTab() {
  const [findings, setFindings] = useState<AZFinding[]>([])
  const [summary, setSummary] = useState<AZSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [resourceTypeFilter, setResourceTypeFilter] = useState<string>('')
  const [redundancyFilter, setRedundancyFilter] = useState<string>('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (resourceTypeFilter) params.set('resource_type', resourceTypeFilter)
      if (redundancyFilter !== '') params.set('has_zone_redundancy', redundancyFilter)

      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/compute/az-coverage${params.toString() ? `?${params}` : ''}`),
        fetch('/api/proxy/compute/az-coverage/summary'),
      ])

      if (findingsRes.ok) {
        const data = await findingsRes.json()
        setFindings(Array.isArray(data) ? data : [])
      }
      if (summaryRes.ok) {
        const data = await summaryRes.json()
        setSummary(data)
      }
    } catch {
      // Network errors handled silently
    } finally {
      setLoading(false)
    }
  }, [resourceTypeFilter, redundancyFilter])

  useEffect(() => {
    void fetchData()
  }, [fetchData])

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="flex flex-wrap gap-3 items-center">
        <StatCard label="Total Resources" value={summary?.total ?? 0} />
        <StatCard label="Zone-Redundant" value={summary?.zone_redundant ?? 0} color="var(--accent-green)" />
        <StatCard label="Non-Redundant" value={summary?.non_redundant ?? 0} color="var(--accent-orange)" />
        <div
          className="rounded-lg px-4 py-3 flex flex-col gap-1 min-w-[140px]"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
        >
          <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>AZ Coverage</span>
          <CoverageBar pct={summary?.coverage_pct ?? 0} />
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={resourceTypeFilter}
          onChange={(e) => setResourceTypeFilter(e.target.value)}
          className="text-sm rounded px-2 py-1"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All Types</option>
          <option value="vm">VM</option>
          <option value="vmss">VMSS</option>
        </select>
        <select
          value={redundancyFilter}
          onChange={(e) => setRedundancyFilter(e.target.value)}
          className="text-sm rounded px-2 py-1"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <option value="">All HA Status</option>
          <option value="true">Zone-Redundant</option>
          <option value="false">Non-Redundant</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ color: 'var(--text-secondary)' }} className="text-sm py-8 text-center">
          Loading AZ coverage data…
        </div>
      ) : findings.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)' }} className="text-sm py-8 text-center">
          No AZ coverage data available.
        </div>
      ) : (
        <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Resource Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Location</TableHead>
                <TableHead>Zones</TableHead>
                <TableHead className="text-right">Zone Count</TableHead>
                <TableHead>HA Status</TableHead>
                <TableHead>Severity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {findings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell>
                    <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
                      {f.resource_name}
                    </span>
                    <div className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                      {f.resource_group}
                    </div>
                  </TableCell>
                  <TableCell>
                    <ResourceTypeBadge resourceType={f.resource_type} />
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)' }}>{f.location}</TableCell>
                  <TableCell>
                    <ZonePills zones={f.zones} />
                  </TableCell>
                  <TableCell className="text-right" style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                    {f.zone_count}
                  </TableCell>
                  <TableCell>
                    <HaBadge redundant={f.has_zone_redundancy} />
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={f.severity} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
