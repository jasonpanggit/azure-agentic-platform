'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Lock, RefreshCw, Download, ScanSearch } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LockSeverity = 'high' | 'medium'
type LockStatus = 'no_lock' | 'rg_lock_only' | 'resource_lock'

interface LockFinding {
  finding_id: string
  resource_id: string
  resource_name: string
  resource_type: string
  resource_group: string
  subscription_id: string
  location: string
  lock_status: LockStatus
  severity: LockSeverity
  recommendation: string
  scanned_at: string
}

interface FindingsResponse {
  findings: LockFinding[]
  total: number
  generated_at?: string
  error?: string
}

interface LockSummary {
  total_unprotected: number
  high_count: number
  medium_count: number
  by_resource_type: Record<string, number>
  top_subscriptions: Array<{ subscription_id: string; count: number }>
  error?: string
}

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: LockSeverity }) {
  const style: React.CSSProperties =
    severity === 'high'
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
    <Badge style={style} className="text-xs font-medium uppercase">
      {severity}
    </Badge>
  )
}

function LockStatusChip({ status }: { status: LockStatus }) {
  const label =
    status === 'no_lock'
      ? 'No Lock'
      : status === 'rg_lock_only'
      ? 'RG Lock Only'
      : 'Resource Lock'

  const style: React.CSSProperties =
    status === 'no_lock'
      ? {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      : status === 'rg_lock_only'
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
    <Badge style={style} className="text-xs font-medium whitespace-nowrap">
      {label}
    </Badge>
  )
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string
  value: number | string
  accent?: string
}) {
  return (
    <div
      className="rounded-lg px-4 py-3 flex flex-col gap-0.5"
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
    >
      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
      <span
        className="text-2xl font-semibold tabular-nums"
        style={{ color: accent ?? 'var(--text-primary)' }}
      >
        {value}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface LockAuditTabProps {
  subscriptions?: string[]
}

const RESOURCE_TYPES = [
  'Virtual Machine',
  'Storage Account',
  'Key Vault',
  'Cosmos DB Account',
  'PostgreSQL Flexible Server',
  'SQL Server',
  'Virtual Network',
  'Recovery Services Vault',
]

const AUTO_REFRESH_MS = 5 * 60 * 1000 // 5 minutes

export function LockAuditTab({ subscriptions }: LockAuditTabProps) {
  const [findings, setFindings] = useState<LockFinding[]>([])
  const [summary, setSummary] = useState<LockSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [filterSeverity, setFilterSeverity] = useState<string>('')
  const [filterResourceType, setFilterResourceType] = useState<string>('')
  const [filterSubscription, setFilterSubscription] = useState<string>('')

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setLoading(true)
    setError(null)

    try {
      const params = new URLSearchParams()
      if (filterSeverity) params.set('severity', filterSeverity)
      if (filterResourceType) params.set('resource_type', filterResourceType)
      if (filterSubscription) params.set('subscription_id', filterSubscription)

      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/locks/findings?${params.toString()}`, { signal: ctrl.signal }),
        fetch('/api/proxy/locks/summary', { signal: ctrl.signal }),
      ])

      const findingsData: FindingsResponse = await findingsRes.json()
      const summaryData: LockSummary = await summaryRes.json()

      if (findingsData.error) setError(findingsData.error)
      setFindings(findingsData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError('Failed to load lock audit data')
      }
    } finally {
      setLoading(false)
    }
  }, [filterSeverity, filterResourceType, filterSubscription])

  // Initial load + auto-refresh
  useEffect(() => {
    fetchData()
    const timer = setInterval(fetchData, AUTO_REFRESH_MS)
    return () => {
      clearInterval(timer)
      abortRef.current?.abort()
    }
  }, [fetchData])

  const handleScan = async () => {
    setScanning(true)
    try {
      await fetch('/api/proxy/locks/scan', { method: 'POST' })
      // Brief delay then refresh
      setTimeout(() => fetchData(), 2000)
    } finally {
      setScanning(false)
    }
  }

  const handleDownloadScript = async () => {
    setDownloading(true)
    try {
      const params = new URLSearchParams()
      if (filterSeverity) params.set('severity', filterSeverity)
      if (filterSubscription) params.set('subscription_id', filterSubscription)

      const res = await fetch(`/api/proxy/locks/remediation-script?${params.toString()}`)
      const text = await res.text()
      const blob = new Blob([text], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'lock-remediation.sh'
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(false)
    }
  }

  const subscriptionOptions = subscriptions ?? []

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Lock className="h-5 w-5" style={{ color: 'var(--accent-red)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Resource Lock Audit
          </h2>
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            High-value resources missing delete protection
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-1.5 text-xs"
          >
            <ScanSearch className="h-3.5 w-3.5" />
            {scanning ? 'Scanning…' : 'Run Scan'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadScript}
            disabled={downloading || findings.length === 0}
            className="flex items-center gap-1.5 text-xs"
          >
            <Download className="h-3.5 w-3.5" />
            {downloading ? 'Downloading…' : 'Remediation Script'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {loading && !summary ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))
        ) : (
          <>
            <StatCard
              label="Total Unprotected"
              value={summary?.total_unprotected ?? 0}
              accent="var(--text-primary)"
            />
            <StatCard
              label="High Severity"
              value={summary?.high_count ?? 0}
              accent="var(--accent-red)"
            />
            <StatCard
              label="Medium Severity"
              value={summary?.medium_count ?? 0}
              accent="var(--accent-yellow)"
            />
            <StatCard
              label="Resource Types Affected"
              value={Object.keys(summary?.by_resource_type ?? {}).length}
            />
          </>
        )}
      </div>

      {/* Filters */}
      <div
        className="flex flex-wrap items-center gap-3 rounded-lg px-4 py-3"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
          Filter:
        </span>

        {subscriptionOptions.length > 0 && (
          <select
            value={filterSubscription}
            onChange={(e) => setFilterSubscription(e.target.value)}
            className="text-xs rounded px-2 py-1 outline-none"
            style={{
              background: 'var(--bg-canvas)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="">All Subscriptions</option>
            {subscriptionOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}

        <select
          value={filterSeverity}
          onChange={(e) => setFilterSeverity(e.target.value)}
          className="text-xs rounded px-2 py-1 outline-none"
          style={{
            background: 'var(--bg-canvas)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="">All Severities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
        </select>

        <select
          value={filterResourceType}
          onChange={(e) => setFilterResourceType(e.target.value)}
          className="text-xs rounded px-2 py-1 outline-none"
          style={{
            background: 'var(--bg-canvas)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="">All Resource Types</option>
          {RESOURCE_TYPES.map((rt) => (
            <option key={rt} value={rt}>
              {rt}
            </option>
          ))}
        </select>

        {(filterSeverity || filterResourceType || filterSubscription) && (
          <button
            onClick={() => {
              setFilterSeverity('')
              setFilterResourceType('')
              setFilterSubscription('')
            }}
            className="text-xs"
            style={{ color: 'var(--accent-blue)' }}
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <Table>
          <TableHeader>
            <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Resource Name</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Type</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Resource Group</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Lock Status</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Severity</TableHead>
              <TableHead style={{ color: 'var(--text-secondary)' }}>Recommendation</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center py-10 text-sm"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {error ? 'Failed to load findings.' : 'No lock findings. All resources are protected.'}
                </TableCell>
              </TableRow>
            ) : (
              findings.map((f) => (
                <TableRow
                  key={f.finding_id}
                  style={{ borderBottom: '1px solid var(--border)' }}
                >
                  <TableCell
                    className="font-medium text-sm"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {f.resource_name}
                  </TableCell>
                  <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {f.resource_type}
                  </TableCell>
                  <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {f.resource_group}
                  </TableCell>
                  <TableCell>
                    <LockStatusChip status={f.lock_status} />
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={f.severity} />
                  </TableCell>
                  <TableCell
                    className="text-xs max-w-xs"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    <span title={f.recommendation} className="line-clamp-2">
                      {f.recommendation}
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>

        {!loading && findings.length > 0 && (
          <div
            className="px-4 py-2 text-xs"
            style={{
              color: 'var(--text-secondary)',
              borderTop: '1px solid var(--border)',
            }}
          >
            {findings.length} finding{findings.length !== 1 ? 's' : ''} · Auto-refreshes every 5 min
          </div>
        )}
      </div>
    </div>
  )
}
