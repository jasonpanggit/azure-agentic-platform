'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { GitCommitHorizontal, RefreshCw, ScanSearch } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ChangeType = 'Create' | 'Update' | 'Delete' | string

interface ChangeRecord {
  change_id: string
  subscription_id: string
  resource_id: string
  resource_name: string
  resource_type: string
  change_type: ChangeType
  changed_by: string
  timestamp: string
  resource_group: string
  impact_score: number
  impact_reason: string
  captured_at: string
}

interface ChangesResponse {
  changes: ChangeRecord[]
  total: number
  generated_at?: string
  error?: string
}

interface ChangeSummary {
  total: number
  deletes: number
  creates: number
  updates: number
  high_impact_count: number
  top_changers: Array<{ changed_by: string; count: number }>
  error?: string
}

interface Props {
  subscriptions?: string[]
}

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function ChangeTypeBadge({ changeType }: { changeType: ChangeType }) {
  const ct = changeType.toLowerCase()

  let bg: string
  let color: string
  let border: string

  if (ct === 'delete') {
    bg = 'color-mix(in srgb, var(--accent-red) 15%, transparent)'
    color = 'var(--accent-red)'
    border = '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)'
  } else if (ct === 'create') {
    bg = 'color-mix(in srgb, var(--accent-green) 15%, transparent)'
    color = 'var(--accent-green)'
    border = '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)'
  } else {
    bg = 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
    color = 'var(--accent-blue)'
    border = '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)'
  }

  return (
    <Badge
      style={{ background: bg, color, border }}
      className="text-xs font-medium uppercase"
    >
      {changeType}
    </Badge>
  )
}

function ImpactBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    score >= 0.8
      ? 'var(--accent-red)'
      : score >= 0.6
      ? 'var(--accent-yellow)'
      : 'var(--accent-blue)'

  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div
        className="flex-1 rounded-full overflow-hidden"
        style={{ height: 6, background: 'var(--bg-subtle)' }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: color,
            borderRadius: 9999,
            transition: 'width 0.3s ease',
          }}
        />
      </div>
      <span className="text-xs tabular-nums" style={{ color: 'var(--text-secondary)', minWidth: 28 }}>
        {pct}%
      </span>
    </div>
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
      <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
      <span
        className="text-2xl font-bold tabular-nums"
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

export function ChangeIntelligenceTab({ subscriptions = [] }: Props) {
  const [summary, setSummary] = useState<ChangeSummary | null>(null)
  const [changes, setChanges] = useState<ChangeRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [filterChangeType, setFilterChangeType] = useState<string>('')
  const [minImpact, setMinImpact] = useState<number>(0)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch('/api/proxy/changes/summary', { cache: 'no-store' })
      const data: ChangeSummary = await res.json()
      if (!res.ok) {
        setSummary(null)
      } else {
        setSummary(data)
      }
    } catch {
      setSummary(null)
    }
  }, [])

  const fetchChanges = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (filterChangeType) params.set('change_type', filterChangeType)
      if (minImpact > 0) params.set('min_impact', String(minImpact))
      if (subscriptions.length === 1) params.set('subscription_id', subscriptions[0])

      const res = await fetch(`/api/proxy/changes?${params.toString()}`, { cache: 'no-store' })
      const data: ChangesResponse = await res.json()

      if (!res.ok || data.error) {
        setError(data.error ?? `HTTP ${res.status}`)
        setChanges([])
      } else {
        setError(null)
        setChanges(data.changes ?? [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
      setChanges([])
    }
  }, [filterChangeType, minImpact, subscriptions])

  const refresh = useCallback(async () => {
    setLoading(true)
    await Promise.all([fetchSummary(), fetchChanges()])
    setLoading(false)
  }, [fetchSummary, fetchChanges])

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, 5 * 60 * 1000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [refresh])

  async function triggerScan() {
    setScanning(true)
    try {
      await fetch('/api/proxy/changes/scan', { method: 'POST' })
      setTimeout(refresh, 2000)
    } finally {
      setScanning(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitCommitHorizontal
            className="h-5 w-5"
            style={{ color: 'var(--accent-blue)' }}
          />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Change Intelligence
          </h2>
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            Last 24 hours
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={loading}
            className="gap-1.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={triggerScan}
            disabled={scanning}
            className="gap-1.5"
          >
            <ScanSearch className="h-3.5 w-3.5" />
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {loading && !summary ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Total Changes" value={summary?.total ?? 0} />
          <StatCard
            label="High Impact"
            value={summary?.high_impact_count ?? 0}
            accent="var(--accent-yellow)"
          />
          <StatCard
            label="Deletes Today"
            value={summary?.deletes ?? 0}
            accent="var(--accent-red)"
          />
          <StatCard
            label="Active Changers"
            value={summary?.top_changers?.length ?? 0}
          />
        </div>
      )}

      {/* Filters */}
      <div
        className="flex flex-wrap items-center gap-3 rounded-lg px-4 py-3"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
          Filter:
        </span>
        <select
          value={filterChangeType}
          onChange={(e) => setFilterChangeType(e.target.value)}
          className="text-xs rounded px-2 py-1 outline-none"
          style={{
            background: 'var(--bg-subtle)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
          }}
        >
          <option value="">All types</option>
          <option value="Create">Create</option>
          <option value="Update">Update</option>
          <option value="Delete">Delete</option>
        </select>

        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            Min impact:
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={minImpact}
            onChange={(e) => setMinImpact(Number(e.target.value))}
            className="w-24 accent-blue-500"
          />
          <span className="text-xs tabular-nums w-7" style={{ color: 'var(--text-primary)' }}>
            {Math.round(minImpact * 100)}%
          </span>
        </div>

        <Button variant="ghost" size="sm" onClick={refresh} className="ml-auto text-xs">
          Apply
        </Button>
      </div>

      {/* Error state */}
      {error && (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          {error}
        </div>
      )}

      {/* Changes list */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <div
          className="px-4 py-2.5 text-xs font-semibold grid gap-3"
          style={{
            color: 'var(--text-secondary)',
            borderBottom: '1px solid var(--border)',
            gridTemplateColumns: '7rem 1fr 9rem 6rem 9rem 7rem',
          }}
        >
          <span>Time</span>
          <span>Resource</span>
          <span>Type</span>
          <span>Change</span>
          <span>Impact</span>
          <span>Changed by</span>
        </div>

        {loading ? (
          <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {[...Array(6)].map((_, i) => (
              <div key={i} className="px-4 py-3">
                <Skeleton className="h-5 w-full" />
              </div>
            ))}
          </div>
        ) : changes.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm" style={{ color: 'var(--text-secondary)' }}>
            No changes found for current filters. Run a scan to populate data.
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {changes.map((record) => (
              <div
                key={record.change_id}
                className="px-4 py-3 grid gap-3 items-center hover:bg-[var(--bg-subtle)] transition-colors"
                style={{ gridTemplateColumns: '7rem 1fr 9rem 6rem 9rem 7rem' }}
              >
                {/* Timestamp */}
                <span className="text-xs tabular-nums truncate" style={{ color: 'var(--text-secondary)' }}>
                  {record.timestamp
                    ? new Date(record.timestamp).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : '—'}
                </span>

                {/* Resource */}
                <div className="min-w-0">
                  <p
                    className="text-sm font-medium truncate"
                    style={{ color: 'var(--text-primary)' }}
                    title={record.resource_name}
                  >
                    {record.resource_name}
                  </p>
                  <p className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>
                    {record.resource_group}
                  </p>
                </div>

                {/* Resource type */}
                <span
                  className="text-xs truncate"
                  style={{ color: 'var(--text-secondary)' }}
                  title={record.resource_type}
                >
                  {record.resource_type}
                </span>

                {/* Change type chip */}
                <ChangeTypeBadge changeType={record.change_type} />

                {/* Impact bar */}
                <div title={record.impact_reason}>
                  <ImpactBar score={record.impact_score} />
                </div>

                {/* Changed by */}
                <span
                  className="text-xs truncate"
                  style={{ color: 'var(--text-secondary)' }}
                  title={record.changed_by}
                >
                  {record.changed_by}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
