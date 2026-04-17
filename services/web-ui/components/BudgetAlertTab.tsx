'use client'

import { useEffect, useState, useCallback } from 'react'
import { DollarSign, RefreshCw, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface BudgetFinding {
  id: string
  subscription_id: string
  budget_name: string
  budget_amount: number
  current_spend: number
  forecast_spend: number
  spend_pct: number
  status: 'no_budget' | 'on_track' | 'warning' | 'exceeded'
  time_period_start: string
  time_period_end: string
  scanned_at: string
}

interface BudgetSummary {
  total_budgets: number
  exceeded_count: number
  warning_count: number
  on_track_count: number
  no_budget_count: number
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000

function StatusBadge({ status }: { status: string }) {
  const style: React.CSSProperties =
    status === 'exceeded'
      ? {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      : status === 'warning'
      ? {
          background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
          color: 'var(--accent-yellow)',
          border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
        }
      : status === 'on_track'
      ? {
          background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
          color: 'var(--accent-green)',
          border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
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
      {status.replace('_', ' ')}
    </span>
  )
}

function SpendBar({ pct }: { pct: number }) {
  const clipped = Math.min(Math.max(pct, 0), 100)
  const color =
    pct >= 100
      ? 'var(--accent-red)'
      : pct >= 80
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

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(2)}`
}

export default function BudgetAlertTab() {
  const [findings, setFindings] = useState<BudgetFinding[]>([])
  const [summary, setSummary] = useState<BudgetSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      const qs = params.toString()

      const [budgetsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/budgets${qs ? `?${qs}` : ''}`),
        fetch('/api/proxy/budgets/summary'),
      ])

      if (!budgetsRes.ok) {
        const d = await budgetsRes.json()
        throw new Error(d?.error ?? `HTTP ${budgetsRes.status}`)
      }
      if (!summaryRes.ok) {
        const d = await summaryRes.json()
        throw new Error(d?.error ?? `HTTP ${summaryRes.status}`)
      }

      const budgetsData = await budgetsRes.json()
      const summaryData = await summaryRes.json()

      setFindings(budgetsData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleScan = async () => {
    setScanning(true)
    try {
      const res = await fetch('/api/proxy/budgets/scan', { method: 'POST' })
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
          <DollarSign
            size={20}
            style={{ color: 'var(--accent-green)' }}
            aria-label="Budget alert icon"
          />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Subscription Budget & Spending
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
          <SummaryCard label="No Budget" value={summary.no_budget_count} accentVar="var(--text-secondary)" />
          <SummaryCard label="Warning" value={summary.warning_count} accentVar="var(--accent-yellow)" />
          <SummaryCard label="Exceeded" value={summary.exceeded_count} accentVar="var(--accent-red)" />
          <SummaryCard label="On Track" value={summary.on_track_count} accentVar="var(--accent-green)" />
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
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All Statuses</option>
          <option value="exceeded">Exceeded</option>
          <option value="warning">Warning</option>
          <option value="on_track">On Track</option>
          <option value="no_budget">No Budget</option>
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Subscription</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Budget Name</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Budget Amount</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Current Spend</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Forecast</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Spend %</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  Loading…
                </TableCell>
              </TableRow>
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  No budget findings. Run a scan to populate data.
                </TableCell>
              </TableRow>
            ) : (
              findings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell
                    className="font-mono text-xs max-w-[140px] truncate"
                    style={{ color: 'var(--text-secondary)' }}
                    title={f.subscription_id}
                  >
                    {f.subscription_id}
                  </TableCell>
                  <TableCell className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                    {f.budget_name === 'NO_BUDGET' ? (
                      <span style={{ color: 'var(--text-secondary)' }}>—</span>
                    ) : (
                      f.budget_name
                    )}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums" style={{ color: 'var(--text-primary)' }}>
                    {f.budget_amount > 0 ? formatCurrency(f.budget_amount) : '—'}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums" style={{ color: 'var(--text-primary)' }}>
                    {f.current_spend > 0 ? formatCurrency(f.current_spend) : '—'}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                    {f.forecast_spend > 0 ? formatCurrency(f.forecast_spend) : '—'}
                  </TableCell>
                  <TableCell className="min-w-[160px]">
                    {f.status === 'no_budget' ? (
                      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>N/A</span>
                    ) : (
                      <SpendBar pct={f.spend_pct} />
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={f.status} />
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
