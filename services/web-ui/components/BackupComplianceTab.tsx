'use client'

import { useState, useEffect, useCallback } from 'react'
import { ShieldCheck, RefreshCw, AlertTriangle, CheckCircle, Database } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

// ── Types ─────────────────────────────────────────────────────────────────────

interface BackupFinding {
  readonly finding_id: string
  readonly resource_id: string
  readonly resource_name: string
  readonly resource_group: string
  readonly subscription_id: string
  readonly location: string
  readonly backup_status: 'protected' | 'unprotected' | 'unhealthy'
  readonly backup_policy: string
  readonly last_backup_time: string
  readonly last_backup_status: string
  readonly severity: 'critical' | 'high' | 'info'
  readonly scanned_at: string
}

interface BackupSummary {
  readonly total_vms: number
  readonly protected: number
  readonly unprotected: number
  readonly unhealthy: number
  readonly protection_rate: number
  readonly recent_failures: number
}

interface BackupComplianceTabProps {
  subscriptions?: string[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityColor(severity: string): string {
  switch (severity) {
    case 'critical': return 'var(--accent-red)'
    case 'high':     return 'var(--accent-orange, var(--accent-yellow))'
    case 'info':     return 'var(--accent-green)'
    default:         return 'var(--text-muted)'
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'protected':   return 'var(--accent-green)'
    case 'unprotected': return 'var(--accent-red)'
    case 'unhealthy':   return 'var(--accent-yellow)'
    default:            return 'var(--text-muted)'
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = severityColor(severity)
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {severity.toUpperCase()}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const color = statusColor(status)
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {status}
    </span>
  )
}

function formatLastBackup(isoStr: string): string {
  if (!isoStr) return '—'
  try {
    return new Date(isoStr).toLocaleString()
  } catch {
    return isoStr
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BackupComplianceTab({ subscriptions = [] }: BackupComplianceTabProps) {
  const [findings, setFindings] = useState<BackupFinding[]>([])
  const [summary, setSummary] = useState<BackupSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [filterSubscription, setFilterSubscription] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (filterSubscription) params.set('subscription_id', filterSubscription)
      if (filterStatus) params.set('backup_status', filterStatus)

      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/backup/findings${params.toString() ? `?${params}` : ''}`),
        fetch('/api/proxy/backup/summary'),
      ])

      if (!findingsRes.ok) throw new Error(`Findings error: ${findingsRes.status}`)
      if (!summaryRes.ok) throw new Error(`Summary error: ${summaryRes.status}`)

      const findingsData = await findingsRes.json()
      const summaryData = await summaryRes.json()

      setFindings(findingsData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load backup compliance data')
    } finally {
      setLoading(false)
    }
  }, [filterSubscription, filterStatus])

  // Initial load + auto-refresh every 10 minutes
  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleScan = async () => {
    setScanning(true)
    try {
      const params = new URLSearchParams()
      if (filterSubscription) params.set('subscription_id', filterSubscription)
      await fetch(`/api/proxy/backup/scan${params.toString() ? `?${params}` : ''}`, { method: 'POST' })
      // Refresh after a short delay to let the scan start
      setTimeout(fetchData, 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const protectionRate = summary?.protection_rate ?? 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Backup Compliance
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-1.5"
          >
            <Database className="h-3.5 w-3.5" />
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Total VMs</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--text-primary)' }}>{summary.total_vms}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Protected</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--accent-green)' }}>{summary.protected}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Unprotected</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--accent-red)' }}>{summary.unprotected}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Failed Backups</p>
            <p className="text-2xl font-bold mt-1" style={{ color: summary.recent_failures > 0 ? 'var(--accent-yellow)' : 'var(--text-primary)' }}>
              {summary.recent_failures}
            </p>
          </div>
        </div>
      )}

      {/* Protection rate progress bar */}
      {summary && (
        <div className="rounded-lg p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Protection Rate
            </span>
            <span className="text-sm font-semibold" style={{ color: protectionRate >= 80 ? 'var(--accent-green)' : protectionRate >= 50 ? 'var(--accent-yellow)' : 'var(--accent-red)' }}>
              {protectionRate.toFixed(1)}%
            </span>
          </div>
          <div
            className="w-full rounded-full overflow-hidden"
            style={{ height: 8, background: 'var(--bg-subtle, var(--border))' }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(protectionRate, 100)}%`,
                background: protectionRate >= 80
                  ? 'var(--accent-green)'
                  : protectionRate >= 50
                    ? 'var(--accent-yellow)'
                    : 'var(--accent-red)',
              }}
            />
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <input
          type="text"
          placeholder="Filter by subscription ID…"
          value={filterSubscription}
          onChange={e => setFilterSubscription(e.target.value)}
          className="rounded-md px-3 py-1.5 text-sm outline-none"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
            minWidth: 220,
          }}
        />
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          className="rounded-md px-3 py-1.5 text-sm outline-none"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="">All statuses</option>
          <option value="protected">Protected</option>
          <option value="unprotected">Unprotected</option>
          <option value="unhealthy">Unhealthy</option>
        </select>
        <Button variant="outline" size="sm" onClick={fetchData}>Apply</Button>
      </div>

      {/* Error */}
      {error && (
        <div
          className="flex items-center gap-2 rounded-md px-3 py-2 text-sm"
          style={{ background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)', color: 'var(--accent-red)', border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)' }}
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>VM Name</TableHead>
              <TableHead>Resource Group</TableHead>
              <TableHead>Backup Status</TableHead>
              <TableHead>Policy</TableHead>
              <TableHead>Last Backup</TableHead>
              <TableHead>Last Status</TableHead>
              <TableHead>Severity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && findings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  Loading…
                </TableCell>
              </TableRow>
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  No findings. Run a scan to populate data.
                </TableCell>
              </TableRow>
            ) : (
              findings.map(f => (
                <TableRow key={f.finding_id}>
                  <TableCell className="font-medium" style={{ color: 'var(--text-primary)' }}>
                    {f.resource_name || '—'}
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)' }}>
                    {f.resource_group || '—'}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={f.backup_status} />
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)' }}>
                    {f.backup_policy || '—'}
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                    {formatLastBackup(f.last_backup_time)}
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)' }}>
                    {f.last_backup_status || '—'}
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

      {findings.length > 0 && (
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          Showing {findings.length} VM{findings.length !== 1 ? 's' : ''}
        </p>
      )}
    </div>
  )
}
