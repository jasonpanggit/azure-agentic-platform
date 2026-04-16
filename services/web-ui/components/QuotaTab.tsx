'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
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
import { Input } from '@/components/ui/input'
import { BarChart3, RefreshCw, ChevronLeft, ChevronRight, X } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TrafficLight = 'red' | 'yellow' | 'green'
type ResourceTypeFilter = 'all' | 'compute' | 'network' | 'storage'

interface QuotaItem {
  quota_name: string
  display_name: string
  category: string
  current_value: number
  limit: number
  usage_pct: number
  available: number
  traffic_light: TrafficLight
  days_to_exhaustion?: number | null
  growth_rate_per_day?: number | null
}

interface QuotaListResponse {
  quotas: QuotaItem[]
  pagination: {
    page: number
    page_size: number
    total: number
    total_pages: number
  }
  generated_at?: string
  warnings?: string[]
  error?: string
}

interface QuotaSummaryResponse {
  total: number
  critical: number
  warning: number
  healthy: number
  top_constrained: QuotaItem[]
  error?: string
}

interface QuotaIncreasePayload {
  subscription_id: string
  location: string
  quota_name: string
  resource_type: string
  current_limit: number
  requested_limit: number
  justification: string
}

// ---------------------------------------------------------------------------
// Traffic badge — CSS semantic tokens only
// ---------------------------------------------------------------------------

function TrafficBadge({ light }: { light: TrafficLight }) {
  const styles: Record<TrafficLight, React.CSSProperties> = {
    red: {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
    },
    yellow: {
      background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
      color: 'var(--accent-yellow)',
      border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
    },
    green: {
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
      border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
    },
  }
  const labels: Record<TrafficLight, string> = {
    red: 'Critical',
    yellow: 'Warning',
    green: 'Healthy',
  }
  return <Badge style={styles[light]}>{labels[light]}</Badge>
}

// ---------------------------------------------------------------------------
// Progress bar — CSS semantic tokens only
// ---------------------------------------------------------------------------

function UsageBar({ pct, light }: { pct: number; light: TrafficLight }) {
  const colorVar =
    light === 'red'
      ? 'var(--accent-red)'
      : light === 'yellow'
      ? 'var(--accent-yellow)'
      : 'var(--accent-green)'

  return (
    <div
      className="w-24 h-2 rounded-full overflow-hidden"
      style={{ background: 'var(--bg-subtle)' }}
    >
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${Math.min(100, pct)}%`, background: colorVar }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary stat cards
// ---------------------------------------------------------------------------

interface StatCardProps {
  label: string
  value: number
  accentVar?: string
}

function StatCard({ label, value, accentVar }: StatCardProps) {
  return (
    <Card style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
      <CardContent className="p-4">
        <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
          {label}
        </p>
        <p
          className="text-2xl font-bold"
          style={{ color: accentVar ?? 'var(--text-primary)' }}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Request Increase Modal
// ---------------------------------------------------------------------------

interface IncreaseModalProps {
  quota: QuotaItem
  subscriptionId: string
  location: string
  onClose: () => void
  onSuccess: (requestId: string) => void
}

function RequestIncreaseModal({
  quota,
  subscriptionId,
  location,
  onClose,
  onSuccess,
}: IncreaseModalProps) {
  const [requestedLimit, setRequestedLimit] = useState<number>(quota.limit * 2)
  const [justification, setJustification] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    const payload: QuotaIncreasePayload = {
      subscription_id: subscriptionId,
      location,
      quota_name: quota.quota_name,
      resource_type: quota.category,
      current_limit: quota.limit,
      requested_limit: requestedLimit,
      justification,
    }

    try {
      const res = await fetch('/api/proxy/quotas/request-increase', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(15000),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data?.error ?? `Request failed: ${res.status}`)
        return
      }
      onSuccess(data.request_id ?? 'submitted')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0"
        style={{ background: 'rgba(0,0,0,0.4)' }}
        onClick={onClose}
      />
      {/* Modal */}
      <div
        className="relative z-10 w-full max-w-md rounded-xl p-6 shadow-xl"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Request Quota Increase
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 transition-colors"
            style={{ color: 'var(--text-secondary)' }}
            aria-label="Close modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-4 p-3 rounded-lg" style={{ background: 'var(--bg-subtle)' }}>
          <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
            Quota
          </p>
          <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
            {quota.display_name || quota.quota_name}
          </p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
            Current limit: <strong>{quota.limit.toLocaleString()}</strong> &nbsp;|&nbsp;
            Used: <strong>{quota.current_value.toLocaleString()}</strong> ({quota.usage_pct}%)
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              className="block text-xs font-medium mb-1"
              style={{ color: 'var(--text-secondary)' }}
            >
              Requested New Limit
            </label>
            <Input
              type="number"
              min={quota.limit + 1}
              value={requestedLimit}
              onChange={(e) => setRequestedLimit(Number(e.target.value))}
              required
            />
          </div>

          <div>
            <label
              className="block text-xs font-medium mb-1"
              style={{ color: 'var(--text-secondary)' }}
            >
              Justification
            </label>
            <textarea
              className="w-full rounded-md border px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2"
              style={{
                background: 'var(--bg-canvas)',
                borderColor: 'var(--border)',
                color: 'var(--text-primary)',
                minHeight: 80,
              }}
              placeholder="Describe the business need for this increase..."
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              minLength={10}
              required
            />
          </div>

          {error && (
            <p className="text-xs" style={{ color: 'var(--accent-red)' }}>
              {error}
            </p>
          )}

          <div className="flex gap-2 justify-end">
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Submitting…' : 'Submit Request'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main QuotaTab component
// ---------------------------------------------------------------------------

interface QuotaTabProps {
  subscriptionId?: string
}

const LOCATIONS = [
  'eastus', 'eastus2', 'westus', 'westus2', 'westus3',
  'centralus', 'northcentralus', 'southcentralus',
  'westeurope', 'northeurope', 'uksouth', 'ukwest',
  'australiaeast', 'southeastasia', 'eastasia',
  'japaneast', 'brazilsouth', 'canadacentral',
]

const RESOURCE_TYPE_OPTIONS: { value: ResourceTypeFilter; label: string }[] = [
  { value: 'all', label: 'All Types' },
  { value: 'compute', label: 'Compute' },
  { value: 'network', label: 'Network' },
  { value: 'storage', label: 'Storage' },
]

export function QuotaTab({ subscriptionId }: QuotaTabProps) {
  const [location, setLocation] = useState('eastus')
  const [resourceType, setResourceType] = useState<ResourceTypeFilter>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 50

  const [listData, setListData] = useState<QuotaListResponse | null>(null)
  const [summaryData, setSummaryData] = useState<QuotaSummaryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [increaseModal, setIncreaseModal] = useState<QuotaItem | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    if (!subscriptionId) return
    setLoading(true)
    setError(null)

    const params = new URLSearchParams({
      subscription_id: subscriptionId,
      location,
      page: String(page),
      page_size: String(PAGE_SIZE),
    })
    if (resourceType !== 'all') params.set('resource_type', resourceType)
    if (search.trim()) params.set('search', search.trim())

    const summaryParams = new URLSearchParams({
      subscription_id: subscriptionId,
      location,
    })

    try {
      const [listRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/quotas?${params}`),
        fetch(`/api/proxy/quotas/summary?${summaryParams}`),
      ])
      const [list, summary] = await Promise.all([listRes.json(), summaryRes.json()])
      setListData(list)
      setSummaryData(summary)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId, location, resourceType, search, page])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1)
  }, [subscriptionId, location, resourceType, search])

  function handleIncreaseSuccess(requestId: string) {
    setIncreaseModal(null)
    setSuccessMessage(`Quota increase request submitted (ID: ${requestId})`)
    setTimeout(() => setSuccessMessage(null), 6000)
  }

  const quotas = listData?.quotas ?? []
  const pagination = listData?.pagination
  const canPrev = page > 1
  const canNext = pagination ? page < pagination.total_pages : false

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h1 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Quota Management
          </h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Location selector */}
          <select
            className="rounded-md border px-2 py-1.5 text-sm focus:outline-none focus:ring-2"
            style={{
              background: 'var(--bg-surface)',
              borderColor: 'var(--border)',
              color: 'var(--text-primary)',
            }}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            aria-label="Location"
          >
            {LOCATIONS.map((loc) => (
              <option key={loc} value={loc}>{loc}</option>
            ))}
          </select>

          {/* Resource type filter */}
          <select
            className="rounded-md border px-2 py-1.5 text-sm focus:outline-none focus:ring-2"
            style={{
              background: 'var(--bg-surface)',
              borderColor: 'var(--border)',
              color: 'var(--text-primary)',
            }}
            value={resourceType}
            onChange={(e) => setResourceType(e.target.value as ResourceTypeFilter)}
            aria-label="Resource type"
          >
            {RESOURCE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>

          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="gap-1.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Success message */}
      {successMessage && (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
            color: 'var(--accent-green)',
            border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
          }}
        >
          {successMessage}
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
            color: 'var(--accent-red)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
          }}
        >
          {error}
        </div>
      )}

      {/* Summary cards */}
      {!subscriptionId ? (
        <div
          className="rounded-lg px-4 py-8 text-center text-sm"
          style={{ color: 'var(--text-secondary)', background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          Select a subscription to view quota data.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {loading && !summaryData ? (
              Array.from({ length: 4 }).map((_, i) => (
                <Card key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                  <CardContent className="p-4">
                    <Skeleton className="h-3 w-20 mb-2" />
                    <Skeleton className="h-7 w-12" />
                  </CardContent>
                </Card>
              ))
            ) : (
              <>
                <StatCard label="Total Quotas" value={summaryData?.total ?? 0} />
                <StatCard
                  label="Critical"
                  value={summaryData?.critical ?? 0}
                  accentVar="var(--accent-red)"
                />
                <StatCard
                  label="Warning"
                  value={summaryData?.warning ?? 0}
                  accentVar="var(--accent-yellow)"
                />
                <StatCard
                  label="Healthy"
                  value={summaryData?.healthy ?? 0}
                  accentVar="var(--accent-green)"
                />
              </>
            )}
          </div>

          {/* Search bar */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1 max-w-sm">
              <Input
                placeholder="Search quotas by name…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pr-8"
              />
              {search && (
                <button
                  className="absolute right-2 top-1/2 -translate-y-1/2"
                  style={{ color: 'var(--text-secondary)' }}
                  onClick={() => setSearch('')}
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {pagination && (
              <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                {pagination.total} quota{pagination.total !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {/* Main table */}
          <div
            className="rounded-lg overflow-hidden"
            style={{ border: '1px solid var(--border)' }}
          >
            <Table>
              <TableHeader>
                <TableRow style={{ background: 'var(--bg-subtle)' }}>
                  <TableHead style={{ color: 'var(--text-secondary)' }}>Category</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }}>Quota Name</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }} className="text-right">Used</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }} className="text-right">Limit</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }} className="text-right">Available</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }}>Usage %</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }}></TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }}>Status</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)' }}>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && quotas.length === 0 ? (
                  Array.from({ length: 8 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 9 }).map((_, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-full" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : quotas.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={9}
                      className="text-center py-12 text-sm"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      No quota data available for this subscription/location.
                    </TableCell>
                  </TableRow>
                ) : (
                  quotas.map((q) => (
                    <TableRow
                      key={`${q.category}-${q.quota_name}`}
                      style={{ borderBottom: '1px solid var(--border)' }}
                    >
                      <TableCell>
                        <span
                          className="text-xs capitalize px-1.5 py-0.5 rounded"
                          style={{
                            background: 'var(--bg-subtle)',
                            color: 'var(--text-secondary)',
                          }}
                        >
                          {q.category}
                        </span>
                      </TableCell>
                      <TableCell
                        className="text-sm font-medium max-w-[200px] truncate"
                        style={{ color: 'var(--text-primary)' }}
                        title={q.display_name || q.quota_name}
                      >
                        {q.display_name || q.quota_name}
                      </TableCell>
                      <TableCell
                        className="text-right text-sm tabular-nums"
                        style={{ color: 'var(--text-primary)' }}
                      >
                        {q.current_value.toLocaleString()}
                      </TableCell>
                      <TableCell
                        className="text-right text-sm tabular-nums"
                        style={{ color: 'var(--text-primary)' }}
                      >
                        {q.limit.toLocaleString()}
                      </TableCell>
                      <TableCell
                        className="text-right text-sm tabular-nums"
                        style={{ color: 'var(--text-secondary)' }}
                      >
                        {q.available.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-sm tabular-nums" style={{ color: 'var(--text-primary)' }}>
                        {q.usage_pct.toFixed(1)}%
                      </TableCell>
                      <TableCell>
                        <UsageBar pct={q.usage_pct} light={q.traffic_light} />
                      </TableCell>
                      <TableCell>
                        <TrafficBadge light={q.traffic_light} />
                      </TableCell>
                      <TableCell>
                        {(q.traffic_light === 'red' || q.traffic_light === 'yellow') && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-xs"
                            onClick={() => setIncreaseModal(q)}
                          >
                            Request Increase
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          {pagination && pagination.total_pages > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                Page {pagination.page} of {pagination.total_pages} &nbsp;({pagination.total} total)
              </span>
              <div className="flex gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!canPrev}
                  onClick={() => setPage((p) => p - 1)}
                  aria-label="Previous page"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!canNext}
                  onClick={() => setPage((p) => p + 1)}
                  aria-label="Next page"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Request Increase Modal */}
      {increaseModal && subscriptionId && (
        <RequestIncreaseModal
          quota={increaseModal}
          subscriptionId={subscriptionId}
          location={location}
          onClose={() => setIncreaseModal(null)}
          onSuccess={handleIncreaseSuccess}
        />
      )}
    </div>
  )
}
