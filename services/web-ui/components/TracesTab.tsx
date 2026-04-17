'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { GitCommitHorizontal, RefreshCw, Copy, Check } from 'lucide-react'
import { AgentTraceCollapse, TraceStep, TokenUsage } from './AgentTraceCollapse'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TraceSummary {
  id: string
  thread_id: string
  run_id: string
  incident_id?: string | null
  conversation_id?: string | null
  agent_name: string
  captured_at: string
  total_tool_calls: number
  duration_ms?: number | null
  token_usage?: TokenUsage | null
}

interface TraceDetail extends TraceSummary {
  steps: TraceStep[]
}

interface TraceListResponse {
  traces: TraceSummary[]
  total: number
  generated_at: string
}

interface TracesTabProps {
  subscriptionId?: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCapturedAt(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return iso
  }
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={e => { e.stopPropagation(); copy() }}
      className="ml-1 opacity-50 hover:opacity-100 transition-opacity"
      title="Copy thread ID"
    >
      {copied ? <Check className="w-3 h-3" style={{ color: 'var(--accent-green)' }} /> : <Copy className="w-3 h-3" />}
    </button>
  )
}

function TokenChip({ usage }: { usage?: TokenUsage | null }) {
  if (!usage || usage.total_tokens === 0) return null
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs"
      style={{
        background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
        color: 'var(--accent-blue)',
      }}
    >
      {usage.total_tokens.toLocaleString()} tokens
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TracesTab({ subscriptionId }: TracesTabProps) {
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [expandedDetail, setExpandedDetail] = useState<TraceDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Filters
  const [threadIdFilter, setThreadIdFilter] = useState('')
  const [incidentIdFilter, setIncidentIdFilter] = useState('')
  const [limit, setLimit] = useState('50')

  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const generatedAtRef = useRef<string | null>(null)

  const buildQuery = useCallback(() => {
    const params = new URLSearchParams()
    if (threadIdFilter.trim()) params.set('thread_id', threadIdFilter.trim())
    if (incidentIdFilter.trim()) params.set('incident_id', incidentIdFilter.trim())
    params.set('limit', limit)
    return params.toString()
  }, [threadIdFilter, incidentIdFilter, limit])

  const fetchTraces = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const qs = buildQuery()
      const res = await fetch(`/api/proxy/traces${qs ? `?${qs}` : ''}`, {
        signal: AbortSignal.timeout(15000),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: TraceListResponse = await res.json()
      setTraces(data.traces ?? [])
      setTotal(data.total ?? 0)
      generatedAtRef.current = data.generated_at
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load traces')
    } finally {
      setLoading(false)
    }
  }, [buildQuery])

  const fetchDetail = useCallback(async (trace: TraceSummary) => {
    const key = `${trace.thread_id}/${trace.run_id}`
    if (expandedId === key) {
      setExpandedId(null)
      setExpandedDetail(null)
      return
    }
    setExpandedId(key)
    setDetailLoading(true)
    try {
      const res = await fetch(`/api/proxy/traces/${encodeURIComponent(trace.thread_id)}/${encodeURIComponent(trace.run_id)}`, {
        signal: AbortSignal.timeout(10000),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: TraceDetail = await res.json()
      setExpandedDetail(data)
    } catch {
      setExpandedDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }, [expandedId])

  // Initial load + auto-refresh every 60s
  useEffect(() => {
    fetchTraces()
    refreshTimerRef.current = setInterval(fetchTraces, 60000)
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current)
    }
  }, [fetchTraces])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <GitCommitHorizontal className="w-5 h-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Agent Traces
          </h2>
          {total > 0 && (
            <Badge variant="outline" className="text-xs">
              {total.toLocaleString()}
            </Badge>
          )}
        </div>
        <button
          onClick={fetchTraces}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border hover:opacity-80 transition-opacity disabled:opacity-50"
          style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4 pb-3">
          <div className="flex flex-wrap gap-3 items-center">
            <Input
              placeholder="Filter by thread ID…"
              value={threadIdFilter}
              onChange={e => setThreadIdFilter(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && fetchTraces()}
              className="text-xs h-8 w-56"
            />
            <Input
              placeholder="Filter by incident ID…"
              value={incidentIdFilter}
              onChange={e => setIncidentIdFilter(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && fetchTraces()}
              className="text-xs h-8 w-56"
            />
            <Select value={limit} onValueChange={v => setLimit(v)}>
              <SelectTrigger className="w-28 h-8 text-xs">
                <SelectValue placeholder="Limit" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="20">20 rows</SelectItem>
                <SelectItem value="50">50 rows</SelectItem>
                <SelectItem value="100">100 rows</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Error */}
      {error && (
        <p className="text-sm px-1" style={{ color: 'var(--accent-red)' }}>
          Error: {error}
        </p>
      )}

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Captured At</TableHead>
                <TableHead className="text-xs">Agent</TableHead>
                <TableHead className="text-xs">Thread ID</TableHead>
                <TableHead className="text-xs text-right">Tool Calls</TableHead>
                <TableHead className="text-xs text-right">Duration</TableHead>
                <TableHead className="text-xs text-right">Tokens</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && traces.length === 0 && (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 6 }).map((_, j) => (
                      <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                    ))}
                  </TableRow>
                ))
              )}

              {!loading && traces.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-10 text-sm" style={{ color: 'var(--text-secondary)' }}>
                    <GitCommitHorizontal className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    No traces captured yet — agent traces are recorded automatically when conversations run
                  </TableCell>
                </TableRow>
              )}

              {traces.map(trace => {
                const key = `${trace.thread_id}/${trace.run_id}`
                const isExpanded = expandedId === key
                return (
                  <React.Fragment key={key}>
                    <TableRow
                      onClick={() => fetchDetail(trace)}
                      className="cursor-pointer hover:opacity-80 transition-opacity"
                    >
                      <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        {formatCapturedAt(trace.captured_at)}
                      </TableCell>
                      <TableCell>
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                          style={{
                            background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                            color: 'var(--accent-blue)',
                          }}
                        >
                          {trace.agent_name}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>
                        <span title={trace.thread_id}>{truncate(trace.thread_id, 24)}</span>
                        <CopyButton text={trace.thread_id} />
                      </TableCell>
                      <TableCell className="text-xs text-right" style={{ color: 'var(--text-primary)' }}>
                        {trace.total_tool_calls}
                      </TableCell>
                      <TableCell className="text-xs text-right" style={{ color: 'var(--text-secondary)' }}>
                        {trace.duration_ms != null ? `${(trace.duration_ms / 1000).toFixed(2)}s` : '—'}
                      </TableCell>
                      <TableCell className="text-right">
                        <TokenChip usage={trace.token_usage} />
                      </TableCell>
                    </TableRow>

                    {/* Expanded detail row */}
                    {isExpanded && (
                      <TableRow>
                        <TableCell
                          colSpan={6}
                          style={{ background: 'var(--bg-surface)', padding: '0 1rem 0.75rem' }}
                        >
                          {detailLoading && (
                            <div className="space-y-2 py-3">
                              {Array.from({ length: 3 }).map((_, i) => (
                                <Skeleton key={i} className="h-8 w-full" />
                              ))}
                            </div>
                          )}
                          {!detailLoading && expandedDetail && (
                            <AgentTraceCollapse
                              steps={expandedDetail.steps}
                              tokenUsage={expandedDetail.token_usage ?? undefined}
                              durationMs={expandedDetail.duration_ms}
                            />
                          )}
                          {!detailLoading && !expandedDetail && (
                            <p className="text-xs py-2" style={{ color: 'var(--text-secondary)' }}>
                              Could not load trace details.
                            </p>
                          )}
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
