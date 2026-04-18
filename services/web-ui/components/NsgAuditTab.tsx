'use client'

import { useState, useEffect, useCallback } from 'react'
import { Shield, RefreshCw, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Skeleton } from '@/components/ui/skeleton'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NSGFinding {
  finding_id: string
  nsg_id: string
  nsg_name: string
  resource_group: string
  subscription_id: string
  location: string
  rule_name: string
  priority: number
  direction: string
  access: string
  source_address: string
  destination_port: string
  severity: string
  description: string
  remediation: string
  scanned_at: string
}

interface SeverityCounts {
  critical: number
  high: number
  medium: number
  info: number
  total: number
}

interface TopNsg {
  nsg_name: string
  nsg_id: string
  finding_count: number
}

interface Summary {
  counts: SeverityCounts
  top_risky_nsgs: TopNsg[]
  generated_at: string
}

interface FindingsResponse {
  findings: NSGFinding[]
  count: number
}

interface NsgAuditTabProps {
  subscriptions?: string[]
}

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

type Severity = 'critical' | 'high' | 'medium' | 'info'

const SEVERITY_ORDER: Severity[] = ['critical', 'high', 'medium', 'info']

function severityStyle(severity: string): React.CSSProperties {
  switch (severity.toLowerCase()) {
    case 'critical':
      return {
        background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
        color: 'var(--accent-red)',
        border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
      }
    case 'high':
      return {
        background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
        color: 'var(--accent-orange)',
        border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)',
      }
    case 'medium':
      return {
        background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: 'var(--accent-yellow)',
        border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
      }
    case 'info':
    default:
      return {
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
        border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
      }
  }
}

function chipStyle(severity: string): React.CSSProperties {
  return {
    ...severityStyle(severity),
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '4px 12px',
    borderRadius: '9999px',
    fontSize: '0.875rem',
    fontWeight: 600,
    cursor: 'default',
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SeverityChip({ label, count, severity }: { label: string; count: number; severity: string }) {
  return (
    <span style={chipStyle(severity)}>
      {label}: {count}
    </span>
  )
}

function SummaryRow({ summary }: { summary: Summary }) {
  const { counts } = summary
  return (
    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
      <SeverityChip label="Critical" count={counts.critical} severity="critical" />
      <SeverityChip label="High" count={counts.high} severity="high" />
      <SeverityChip label="Medium" count={counts.medium} severity="medium" />
      <SeverityChip label="Info" count={counts.info} severity="info" />
      <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginLeft: 4 }}>
        {counts.total} total findings
      </span>
    </div>
  )
}

function TableSkeleton() {
  return (
    <div style={{ padding: '16px' }}>
      {[...Array(5)].map((_, i) => (
        <Skeleton key={i} className="h-10 w-full mb-2" />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function NsgAuditTab({ subscriptions = [] }: NsgAuditTabProps) {
  const [findings, setFindings] = useState<NSGFinding[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loadingFindings, setLoadingFindings] = useState(false)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const [subscriptionFilter, setSubscriptionFilter] = useState<string>('all')

  const fetchSummary = useCallback(async () => {
    setLoadingSummary(true)
    try {
      const res = await fetch('/api/proxy/nsg/findings/summary', { cache: 'no-store' })
      if (res.ok) {
        const data: Summary = await res.json()
        setSummary(data)
      }
    } catch {
      // summary is non-critical, silent fail
    } finally {
      setLoadingSummary(false)
    }
  }, [])

  const fetchFindings = useCallback(async () => {
    setLoadingFindings(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (severityFilter !== 'all') params.set('severity', severityFilter)
      if (subscriptionFilter !== 'all') params.set('subscription_id', subscriptionFilter)
      const qs = params.toString()
      const url = `/api/proxy/nsg/findings${qs ? `?${qs}` : ''}`
      const res = await fetch(url, { cache: 'no-store' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.error ?? `HTTP ${res.status}`)
      }
      const data: FindingsResponse = await res.json()
      setFindings(data.findings ?? [])
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load NSG findings')
    } finally {
      setLoadingFindings(false)
    }
  }, [severityFilter, subscriptionFilter])

  // Initial load
  useEffect(() => {
    fetchFindings()
    fetchSummary()
  }, [fetchFindings, fetchSummary])

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const id = setInterval(() => {
      fetchFindings()
      fetchSummary()
    }, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetchFindings, fetchSummary])

  // Unique subscriptions from loaded findings for filter dropdown
  const uniqueSubscriptions = Array.from(
    new Set(findings.map((f) => f.subscription_id).filter(Boolean))
  )

  return (
    <TooltipProvider>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Shield size={20} style={{ color: 'var(--accent-blue)' }} />
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
              NSG Security Audit
            </h2>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => { fetchFindings(); fetchSummary() }}
              disabled={loadingFindings}
              style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
            >
              <RefreshCw size={14} className={loadingFindings ? 'animate-spin' : ''} style={{ marginRight: 4 }} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Summary row */}
        {loadingSummary ? (
          <Skeleton className="h-8 w-96" />
        ) : summary ? (
          <SummaryRow summary={summary} />
        ) : null}

        {/* Filter bar */}
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <Select value={severityFilter} onValueChange={setSeverityFilter}>
            <SelectTrigger
              style={{
                width: '180px',
                background: 'var(--bg-surface)',
                borderColor: 'var(--border)',
                color: 'var(--text-primary)',
              }}
            >
              <SelectValue placeholder="Severity" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Severities</SelectItem>
              {SEVERITY_ORDER.map((s) => (
                <SelectItem key={s} value={s} style={{ textTransform: 'capitalize' }}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {uniqueSubscriptions.length > 0 && (
            <Select value={subscriptionFilter} onValueChange={setSubscriptionFilter}>
              <SelectTrigger
                style={{
                  width: '280px',
                  background: 'var(--bg-surface)',
                  borderColor: 'var(--border)',
                  color: 'var(--text-primary)',
                }}
              >
                <SelectValue placeholder="Subscription" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Subscriptions</SelectItem>
                {uniqueSubscriptions.map((sub) => (
                  <SelectItem key={sub} value={sub}>
                    {sub}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 14px',
              borderRadius: '8px',
              background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
              border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
              color: 'var(--accent-red)',
              fontSize: '0.875rem',
            }}
          >
            <AlertTriangle size={16} />
            {error}
          </div>
        )}

        {/* Findings table */}
        <div
          style={{
            borderRadius: '8px',
            border: '1px solid var(--border)',
            overflow: 'hidden',
            background: 'var(--bg-surface)',
          }}
        >
          {loadingFindings ? (
            <TableSkeleton />
          ) : findings.length === 0 ? (
            <div
              style={{
                padding: '40px',
                textAlign: 'center',
                color: 'var(--text-secondary)',
                fontSize: '0.9rem',
              }}
            >
              <Shield size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
              {error ? 'Unable to load findings.' : 'No NSG findings found.'}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
                  <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>NSG</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Rule</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Port</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Source</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Severity</TableHead>
                  <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Remediation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {findings.map((f) => (
                  <TableRow
                    key={f.finding_id}
                    style={{ borderBottom: '1px solid var(--border)' }}
                  >
                    <TableCell>
                      <div style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: '0.875rem' }}>
                        {f.nsg_name}
                      </div>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                        {f.resource_group}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span style={{ color: 'var(--text-primary)', fontSize: '0.875rem' }}>
                        {f.rule_name}
                      </span>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                        Priority {f.priority}
                      </div>
                    </TableCell>
                    <TableCell>
                      <code
                        style={{
                          fontSize: '0.8rem',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
                          color: 'var(--accent-blue)',
                        }}
                      >
                        {f.destination_port || '*'}
                      </code>
                    </TableCell>
                    <TableCell>
                      <code
                        style={{
                          fontSize: '0.8rem',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: 'color-mix(in srgb, var(--border) 50%, transparent)',
                          color: 'var(--text-primary)',
                        }}
                      >
                        {f.source_address}
                      </code>
                    </TableCell>
                    <TableCell>
                      <Badge
                        style={{
                          ...severityStyle(f.severity),
                          textTransform: 'capitalize',
                          fontWeight: 600,
                          fontSize: '0.75rem',
                        }}
                      >
                        {f.severity}
                      </Badge>
                    </TableCell>
                    <TableCell style={{ maxWidth: '280px' }}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span
                            style={{
                              cursor: 'help',
                              color: 'var(--text-secondary)',
                              fontSize: '0.8rem',
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                            }}
                          >
                            {f.remediation}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent
                          style={{
                            maxWidth: '360px',
                            background: 'var(--bg-surface)',
                            border: '1px solid var(--border)',
                            color: 'var(--text-primary)',
                            fontSize: '0.8rem',
                            padding: '8px 12px',
                            borderRadius: '6px',
                          }}
                        >
                          <p style={{ marginBottom: 6, fontWeight: 500 }}>Finding</p>
                          <p style={{ marginBottom: 8, color: 'var(--text-secondary)' }}>{f.description}</p>
                          <p style={{ fontWeight: 500 }}>Remediation</p>
                          <p style={{ color: 'var(--text-secondary)' }}>{f.remediation}</p>
                        </TooltipContent>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        {!loadingFindings && findings.length > 0 && (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
            Showing {findings.length} finding{findings.length !== 1 ? 's' : ''}
            {summary?.generated_at && (
              <> · Last scanned {new Date(summary.generated_at).toLocaleString()}</>
            )}
          </div>
        )}
      </div>
    </TooltipProvider>
  )
}
