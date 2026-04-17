'use client'

import { useState, useEffect, useCallback } from 'react'
import { Lock, RefreshCw, AlertTriangle } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PEFinding {
  readonly finding_id: string
  readonly resource_id: string
  readonly resource_name: string
  readonly resource_type: string
  readonly resource_group: string
  readonly subscription_id: string
  readonly location: string
  readonly public_access: 'enabled' | 'disabled' | 'unknown'
  readonly has_private_endpoint: boolean
  readonly private_endpoint_count: number
  readonly severity: 'high' | 'medium' | 'info'
  readonly recommendation: string
  readonly scanned_at: string
}

interface PESummary {
  readonly total_resources: number
  readonly high_count: number
  readonly medium_count: number
  readonly info_count: number
  readonly pe_coverage_pct: number
  readonly by_resource_type: Record<string, { total: number; high: number; medium: number; info: number }>
}

interface PrivateEndpointTabProps {
  subscriptions?: string[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityColor(severity: string): string {
  switch (severity) {
    case 'high':   return 'var(--accent-red)'
    case 'medium': return 'var(--accent-yellow)'
    case 'info':   return 'var(--accent-green)'
    default:       return 'var(--text-muted)'
  }
}

function publicAccessColor(access: string): string {
  return access === 'enabled' ? 'var(--accent-red)' : access === 'disabled' ? 'var(--accent-green)' : 'var(--text-muted)'
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

function AccessBadge({ access }: { access: string }) {
  const color = publicAccessColor(access)
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {access}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PrivateEndpointTab({ subscriptions = [] }: PrivateEndpointTabProps) {
  const [findings, setFindings] = useState<PEFinding[]>([])
  const [summary, setSummary] = useState<PESummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [filterSubscription, setFilterSubscription] = useState('')
  const [filterSeverity, setFilterSeverity] = useState('')
  const [filterResourceType, setFilterResourceType] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (filterSubscription) params.set('subscription_id', filterSubscription)
      if (filterSeverity) params.set('severity', filterSeverity)
      if (filterResourceType) params.set('resource_type', filterResourceType)

      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/private-endpoints/findings${params.toString() ? `?${params}` : ''}`),
        fetch('/api/proxy/private-endpoints/summary'),
      ])

      if (!findingsRes.ok) throw new Error(`Findings error: ${findingsRes.status}`)
      if (!summaryRes.ok) throw new Error(`Summary error: ${summaryRes.status}`)

      const findingsData = await findingsRes.json()
      const summaryData = await summaryRes.json()

      setFindings(findingsData.findings ?? [])
      setSummary(summaryData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load private endpoint data')
    } finally {
      setLoading(false)
    }
  }, [filterSubscription, filterSeverity, filterResourceType])

  // Initial load + auto-refresh every 10 minutes
  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  const coveragePct = summary?.pe_coverage_pct ?? 0

  // Unique resource types from findings for filter dropdown
  const resourceTypes = Array.from(new Set(findings.map(f => f.resource_type).filter(Boolean))).sort()

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Lock className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Private Endpoint Audit
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
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Total Checked</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--text-primary)' }}>{summary.total_resources}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>High (Public + No PE)</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--accent-red)' }}>{summary.high_count}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Mixed Mode</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--accent-yellow)' }}>{summary.medium_count}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Compliant</p>
            <p className="text-2xl font-bold mt-1" style={{ color: 'var(--accent-green)' }}>{summary.info_count}</p>
          </div>
        </div>
      )}

      {/* PE coverage bar */}
      {summary && (
        <div className="rounded-lg p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
              Private Endpoint Coverage
            </span>
            <span
              className="text-sm font-semibold"
              style={{ color: coveragePct >= 80 ? 'var(--accent-green)' : coveragePct >= 50 ? 'var(--accent-yellow)' : 'var(--accent-red)' }}
            >
              {coveragePct.toFixed(1)}%
            </span>
          </div>
          <div
            className="w-full rounded-full overflow-hidden"
            style={{ height: 8, background: 'var(--bg-subtle, var(--border))' }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(coveragePct, 100)}%`,
                background: coveragePct >= 80
                  ? 'var(--accent-green)'
                  : coveragePct >= 50
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
          value={filterSeverity}
          onChange={e => setFilterSeverity(e.target.value)}
          className="rounded-md px-3 py-1.5 text-sm outline-none"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="">All severities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="info">Info</option>
        </select>
        <select
          value={filterResourceType}
          onChange={e => setFilterResourceType(e.target.value)}
          className="rounded-md px-3 py-1.5 text-sm outline-none"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="">All resource types</option>
          {resourceTypes.map(rt => (
            <option key={rt} value={rt}>{rt}</option>
          ))}
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
              <TableHead>Resource Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Public Access</TableHead>
              <TableHead>PE Count</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Recommendation</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && findings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  Loading…
                </TableCell>
              </TableRow>
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>
                  No findings. All resources appear compliant or no resources found.
                </TableCell>
              </TableRow>
            ) : (
              findings.map(f => (
                <TableRow key={f.finding_id}>
                  <TableCell className="font-medium" style={{ color: 'var(--text-primary)' }}>
                    {f.resource_name || '—'}
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                    {f.resource_type}
                  </TableCell>
                  <TableCell>
                    <AccessBadge access={f.public_access} />
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)' }}>
                    {f.private_endpoint_count}
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={f.severity} />
                  </TableCell>
                  <TableCell style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', maxWidth: 320 }}>
                    <span title={f.recommendation} className="line-clamp-2">
                      {f.recommendation}
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {findings.length > 0 && (
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          Showing {findings.length} resource{findings.length !== 1 ? 's' : ''}
        </p>
      )}
    </div>
  )
}
