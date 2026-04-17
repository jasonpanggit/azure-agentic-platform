'use client'

import { useState, useEffect, useCallback } from 'react'
import { Tag, Download, RefreshCw, ChevronDown, ChevronRight, AlertCircle, Search } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagComplianceResource {
  resource_id: string
  resource_name: string
  resource_type: string
  resource_group: string
  location: string
  existing_tags: Record<string, string>
  missing_tags: string[]
  is_compliant: boolean
  compliance_pct: number
}

interface ComplianceSummary {
  total: number
  compliant: number
  non_compliant: number
  compliance_pct: number
  missing_tag_frequency: Record<string, number>
  by_resource_type: Record<string, { total: number; compliant: number; non_compliant: number; compliance_pct: number }>
}

interface ComplianceResponse {
  results: TagComplianceResource[]
  summary: ComplianceSummary
  pagination: { page: number; page_size: number; total: number }
  required_tags: string[]
  generated_at: string
}

interface TaggingComplianceTabProps {
  subscriptionId: string
}

type ComplianceFilter = 'all' | 'non_compliant' | 'compliant'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pctColor(pct: number): string {
  if (pct >= 80) return 'var(--accent-green)'
  if (pct >= 50) return 'var(--accent-yellow)'
  return 'var(--accent-red)'
}

function pctBadgeStyle(pct: number): React.CSSProperties {
  const color = pctColor(pct)
  return {
    background: `color-mix(in srgb, ${color} 15%, transparent)`,
    color,
    border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
    borderRadius: 4,
    padding: '2px 8px',
    fontSize: 12,
    fontWeight: 600,
    display: 'inline-block',
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SummaryCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div
      className="rounded-lg p-4 flex flex-col gap-1"
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
    >
      <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{label}</span>
      <span style={{ color: 'var(--text-primary)', fontSize: 22, fontWeight: 700 }}>{value}</span>
      {sub && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{sub}</span>}
    </div>
  )
}

function ProgressBar({ pct }: { pct: number }) {
  const color = pctColor(pct)
  return (
    <div
      className="rounded-full overflow-hidden"
      style={{ height: 6, width: 80, background: 'var(--bg-subtle)' }}
    >
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${Math.min(pct, 100)}%`, background: color }}
      />
    </div>
  )
}

function MissingTagBadge({ tag }: { tag: string }) {
  return (
    <span
      style={{
        background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
        color: 'var(--accent-red)',
        border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
        borderRadius: 4,
        padding: '1px 6px',
        fontSize: 11,
        fontWeight: 500,
        display: 'inline-block',
        marginRight: 4,
        marginBottom: 2,
      }}
    >
      {tag}
    </span>
  )
}

function RequiredTagChip({ tag }: { tag: string }) {
  return (
    <span
      style={{
        background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
        color: 'var(--accent-blue)',
        border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)',
        borderRadius: 4,
        padding: '2px 8px',
        fontSize: 12,
        fontWeight: 500,
        display: 'inline-block',
      }}
    >
      {tag}
    </span>
  )
}

function ResourceTypeBadge({ type }: { type: string }) {
  const short = type.split('/').slice(-1)[0] ?? type
  return (
    <span
      style={{
        background: 'var(--bg-subtle)',
        color: 'var(--text-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        padding: '1px 6px',
        fontSize: 11,
        display: 'inline-block',
        maxWidth: 180,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
      title={type}
    >
      {short}
    </span>
  )
}

function SkeletonRow() {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <td key={i} className="px-4 py-3">
          <div
            className="rounded animate-pulse"
            style={{ height: 14, width: i === 1 ? 140 : i === 2 ? 80 : i === 4 ? 120 : 60, background: 'var(--bg-subtle)' }}
          />
        </td>
      ))}
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TaggingComplianceTab({ subscriptionId }: TaggingComplianceTabProps) {
  const [data, setData] = useState<ComplianceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<ComplianceFilter>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())
  const [scriptLoading, setScriptLoading] = useState(false)

  const PAGE_SIZE = 200

  const fetchData = useCallback(async () => {
    if (!subscriptionId) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        subscription_id: subscriptionId,
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
        compliant_filter: filter,
      })
      const res = await fetch(`/api/proxy/tagging/compliance?${params}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.error ?? `HTTP ${res.status}`)
      }
      const json: ComplianceResponse = await res.json()
      setData(json)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId, filter, page])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Reset page when filter changes
  useEffect(() => {
    setPage(1)
  }, [filter])

  function toggleRow(resourceId: string) {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(resourceId)) {
        next.delete(resourceId)
      } else {
        next.add(resourceId)
      }
      return next
    })
  }

  async function handleDownloadScript() {
    if (!subscriptionId) return
    setScriptLoading(true)
    try {
      const params = new URLSearchParams({ subscription_id: subscriptionId })
      const res = await fetch(`/api/proxy/tagging/remediation-script?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const text = await res.text()
      const blob = new Blob([text], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'tagging-remediation.sh'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Script download failed', err)
    } finally {
      setScriptLoading(false)
    }
  }

  // Client-side search filter
  const displayedResults = (data?.results ?? []).filter((r) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      r.resource_name.toLowerCase().includes(q) ||
      r.resource_group.toLowerCase().includes(q) ||
      r.resource_type.toLowerCase().includes(q)
    )
  })

  const summary = data?.summary
  const requiredTags = data?.required_tags ?? []
  const overallPct = summary?.compliance_pct ?? 0

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col gap-4">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Tag className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 style={{ color: 'var(--text-primary)', fontWeight: 700, fontSize: 18 }}>
            Resource Tagging Compliance
          </h2>
          {summary && (
            <span style={pctBadgeStyle(overallPct)}>{overallPct.toFixed(1)}% Compliant</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleDownloadScript}
            disabled={scriptLoading || !data}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-opacity disabled:opacity-50 cursor-pointer"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
              color: 'var(--accent-blue)',
              border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
            }}
          >
            <Download className="h-3.5 w-3.5" />
            {scriptLoading ? 'Generating…' : 'Generate Fix Script'}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-opacity disabled:opacity-50 cursor-pointer"
            style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Summary cards ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="Total Resources" value={summary?.total ?? '—'} />
        <SummaryCard
          label="Compliant"
          value={summary?.compliant ?? '—'}
          sub={summary ? `${summary.compliance_pct.toFixed(1)}%` : undefined}
        />
        <SummaryCard label="Non-Compliant" value={summary?.non_compliant ?? '—'} />
        <SummaryCard
          label="Compliance %"
          value={summary ? `${summary.compliance_pct.toFixed(1)}%` : '—'}
        />
      </div>

      {/* ── Required tags row ──────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-3 rounded-lg px-4 py-3"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <span style={{ color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500 }}>
          Required Tags:
        </span>
        <div className="flex gap-2 flex-wrap">
          {requiredTags.map((t) => (
            <RequiredTagChip key={t} tag={t} />
          ))}
          {requiredTags.length === 0 && (
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading…</span>
          )}
        </div>
        <div className="ml-auto">
          <button
            disabled
            title="Configure in platform settings"
            className="px-2.5 py-1 rounded text-xs opacity-50 cursor-not-allowed"
            style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}
          >
            Customize
          </button>
        </div>
      </div>

      {/* ── Filter bar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Toggle buttons */}
        <div className="flex rounded overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          {(['all', 'non_compliant', 'compliant'] as ComplianceFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className="px-3 py-1.5 text-sm transition-colors cursor-pointer"
              style={{
                background: filter === f ? 'var(--accent-blue)' : 'var(--bg-surface)',
                color: filter === f ? '#fff' : 'var(--text-secondary)',
                fontWeight: filter === f ? 600 : 400,
                borderRight: f !== 'compliant' ? '1px solid var(--border)' : undefined,
              }}
            >
              {f === 'all' ? 'All' : f === 'non_compliant' ? 'Non-Compliant' : 'Compliant'}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5" style={{ color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Search resources…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 rounded text-sm outline-none"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          />
        </div>

        <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 'auto' }}>
          {displayedResults.length} resource{displayedResults.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* ── Error state ────────────────────────────────────────────────────── */}
      {error && (
        <div
          className="flex items-center gap-2 rounded-lg px-4 py-3"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{error}</span>
          <button
            onClick={fetchData}
            className="ml-auto text-sm underline cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Table ──────────────────────────────────────────────────────────── */}
      <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
        <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)', width: 28 }} />
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Resource Name</th>
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Type</th>
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Resource Group</th>
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Missing Tags</th>
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Compliance</th>
              <th className="px-4 py-2 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>Tags Present</th>
            </tr>
          </thead>
          <tbody>
            {loading && !data && Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} />)}

            {!loading && !error && displayedResults.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center" style={{ color: 'var(--text-muted)' }}>
                  {data ? 'No resources match the current filter.' : 'No data loaded.'}
                </td>
              </tr>
            )}

            {displayedResults.map((r) => {
              const isExpanded = expandedRows.has(r.resource_id)
              const tagCount = Object.keys(r.existing_tags).length
              return (
                <>
                  <tr
                    key={r.resource_id}
                    onClick={() => toggleRow(r.resource_id)}
                    className="cursor-pointer transition-colors"
                    style={{ borderBottom: '1px solid var(--border)' }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-subtle)' }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = '' }}
                  >
                    <td className="px-4 py-3">
                      {isExpanded
                        ? <ChevronDown className="h-3.5 w-3.5" style={{ color: 'var(--text-muted)' }} />
                        : <ChevronRight className="h-3.5 w-3.5" style={{ color: 'var(--text-muted)' }} />
                      }
                    </td>
                    <td className="px-4 py-3 font-medium" style={{ color: 'var(--text-primary)' }}>
                      {r.resource_name}
                    </td>
                    <td className="px-4 py-3">
                      <ResourceTypeBadge type={r.resource_type} />
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-secondary)' }}>
                      {r.resource_group}
                    </td>
                    <td className="px-4 py-3">
                      {r.missing_tags.length === 0
                        ? <span style={{ color: 'var(--accent-green)', fontSize: 12 }}>✓ All present</span>
                        : r.missing_tags.map((t) => <MissingTagBadge key={t} tag={t} />)
                      }
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <ProgressBar pct={r.compliance_pct} />
                        <span style={{ color: pctColor(r.compliance_pct), fontSize: 12, fontWeight: 600, minWidth: 38 }}>
                          {r.compliance_pct.toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                      {tagCount} tag{tagCount !== 1 ? 's' : ''}
                    </td>
                  </tr>

                  {isExpanded && (
                    <tr key={`${r.resource_id}-exp`} style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}>
                      <td colSpan={7} className="px-8 py-3">
                        <div className="flex flex-col gap-2">
                          <span style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 600 }}>
                            Tags on resource:
                          </span>
                          {Object.keys(r.existing_tags).length === 0 ? (
                            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>No tags present.</span>
                          ) : (
                            <div className="flex flex-wrap gap-2">
                              {Object.entries(r.existing_tags).map(([k, v]) => (
                                <span
                                  key={k}
                                  style={{
                                    background: 'var(--bg-surface)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 4,
                                    padding: '2px 8px',
                                    fontSize: 12,
                                    color: 'var(--text-primary)',
                                  }}
                                >
                                  <strong>{k}</strong>: {v}
                                </span>
                              ))}
                            </div>
                          )}
                          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                            {r.resource_id}
                          </span>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ── Pagination ─────────────────────────────────────────────────────── */}
      {data && data.pagination.total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Page {data.pagination.page} · {data.pagination.total} total
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 rounded text-sm disabled:opacity-40 cursor-pointer"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * PAGE_SIZE >= data.pagination.total}
              className="px-3 py-1.5 rounded text-sm disabled:opacity-40 cursor-pointer"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
