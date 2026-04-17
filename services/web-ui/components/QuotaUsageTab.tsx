'use client'

import { useEffect, useState, useCallback } from 'react'
import { BarChart2, RefreshCw, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface QuotaFinding {
  id: string
  subscription_id: string
  location: string
  quota_name: string
  current_value: number
  limit: number
  utilisation_pct: number
  severity: string
  scanned_at: string
}

interface QuotaSummary {
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  total_count: number
  most_constrained: Array<{
    quota_name: string
    location: string
    subscription_id: string
    utilisation_pct: number
    current_value: number
    limit: number
    severity: string
  }>
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000

function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase()
  const style: React.CSSProperties =
    s === 'critical'
      ? {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      : s === 'high'
      ? {
          background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
          color: 'var(--accent-orange)',
          border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)',
        }
      : s === 'medium'
      ? {
          background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
          color: 'var(--accent-yellow)',
          border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
        }
      : {
          background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
          color: 'var(--accent-green)',
          border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
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

function UtilisationBar({ pct }: { pct: number }) {
  const clipped = Math.min(Math.max(pct, 0), 100)
  const color =
    pct >= 90
      ? 'var(--accent-red)'
      : pct >= 75
      ? 'var(--accent-orange)'
      : pct >= 50
      ? 'var(--accent-yellow)'
      : 'var(--accent-green)'
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 rounded-full flex-1 overflow-hidden"
        style={{ background: 'color-mix(in srgb, var(--border) 40%, transparent)' }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${clipped}%`, background: color }}
        />
      </div>
      <span className="text-xs tabular-nums w-12 text-right" style={{ color: 'var(--text-secondary)' }}>
        {pct.toFixed(1)}%
      </span>
    </div>
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

export default function QuotaUsageTab() {
  const [findings, setFindings] = useState<QuotaFinding[]>([])
  const [summary, setSummary] = useState<QuotaSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState('')
  const [locationFilter, setLocationFilter] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (severityFilter) params.set('severity', severityFilter)
      if (locationFilter) params.set('location', locationFilter)
      const qs = params.toString()

      const [usageRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/quota/usage${qs ? `?${qs}` : ''}`),
        fetch('/api/proxy/quota/summary'),
      ])

      if (!usageRes.ok) {
        const d = await usageRes.json()
        throw new Error(d?.error ?? `HTTP ${usageRes.status}`)
      }
      if (!summaryRes.ok) {
        const d = await summaryRes.json()
        throw new Error(d?.error ?? `HTTP ${summaryRes.status}`)
      }

      const usageData = await usageRes.json()
      const summaryData = await summaryRes.json()

      setFindings(usageData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [severityFilter, locationFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleScan = async () => {
    setScanning(true)
    try {
      const res = await fetch('/api/proxy/quota/scan', { method: 'POST' })
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

  const locations = Array.from(new Set(findings.map((f) => f.location))).sort()

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2
            size={20}
            style={{ color: 'var(--accent-blue)' }}
            aria-label="Quota utilisation icon"
          />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Compute Quota Utilisation
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
            <RefreshCw size={14} aria-label="Refresh" className={loading ? 'animate-spin' : ''} />
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
          <SummaryCard label="Critical Quotas" value={summary.critical_count} accentVar="var(--accent-red)" />
          <SummaryCard label="High Quotas" value={summary.high_count} accentVar="var(--accent-orange)" />
          <SummaryCard label="Medium Quotas" value={summary.medium_count} accentVar="var(--accent-yellow)" />
          <SummaryCard label="Total Monitored" value={summary.total_count} accentVar="var(--accent-blue)" />
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <select
          className="rounded border px-2 py-1 text-sm"
          style={{
            background: 'var(--bg-surface)',
            borderColor: 'var(--border)',
            color: 'var(--text-primary)',
          }}
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
        >
          <option value="">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <select
          className="rounded border px-2 py-1 text-sm"
          style={{
            background: 'var(--bg-surface)',
            borderColor: 'var(--border)',
            color: 'var(--text-primary)',
          }}
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value)}
        >
          <option value="">All Locations</option>
          {locations.map((loc) => (
            <option key={loc} value={loc}>
              {loc}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Quota Name</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Location</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Current / Limit</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Utilisation</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Severity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  Loading…
                </TableCell>
              </TableRow>
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  No quota findings above 25% utilisation
                </TableCell>
              </TableRow>
            ) : (
              findings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell
                    className="font-mono text-sm max-w-[200px] truncate"
                    style={{ color: 'var(--text-primary)' }}
                    title={f.quota_name}
                  >
                    {f.quota_name}
                  </TableCell>
                  <TableCell className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                    {f.location}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums" style={{ color: 'var(--text-primary)' }}>
                    {f.current_value.toLocaleString()} / {f.limit.toLocaleString()}
                  </TableCell>
                  <TableCell className="min-w-[160px]">
                    <UtilisationBar pct={f.utilisation_pct} />
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

      {/* Most constrained */}
      {summary && summary.most_constrained.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
            Most Constrained Quotas
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {summary.most_constrained.map((item, idx) => (
              <div
                key={idx}
                className="rounded-lg border p-3 space-y-1"
                style={{ borderColor: 'var(--border)', background: 'var(--bg-surface)' }}
              >
                <div
                  className="text-sm font-medium truncate"
                  style={{ color: 'var(--text-primary)' }}
                  title={item.quota_name}
                >
                  {item.quota_name}
                </div>
                <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {item.location}
                </div>
                <UtilisationBar pct={item.utilisation_pct} />
                <div className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {item.current_value.toLocaleString()} / {item.limit.toLocaleString()}
                  </span>
                  <SeverityBadge severity={item.severity} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
