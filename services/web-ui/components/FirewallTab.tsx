'use client'

import { useState, useEffect, useCallback } from 'react'
import { Flame, RefreshCw, AlertTriangle } from 'lucide-react'
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

interface FirewallRule {
  firewall_id: string
  firewall_name: string
  resource_group: string
  subscription_id: string
  location: string
  sku_tier: string
  threat_intel_mode: string
  policy_id: string
  policy_name: string
  collection_name: string
  collection_priority: number
  action: string
  rule_name: string
  rule_type: string
  source_addresses: string[]
  destination_addresses: string[]
  destination_ports: string[]
  protocols: string[]
}

interface FirewallAuditFinding {
  firewall_name: string
  rule_name: string
  collection_name: string
  issue_type: string
  severity: string
  detail: string
  remediation: string
}

interface AuditSummary {
  critical: number
  high: number
  medium: number
  total: number
}

interface RulesResponse {
  firewalls: unknown[]
  rules: FirewallRule[]
  count: number
}

interface AuditResponse {
  findings: FirewallAuditFinding[]
  summary: AuditSummary
  generated_at: string
}

interface FirewallTabProps {
  subscriptions?: string[]
}

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

type Severity = 'critical' | 'high' | 'medium'
const SEVERITY_ORDER: Severity[] = ['critical', 'high', 'medium']

const REFRESH_INTERVAL_MS = 600_000 // 10 minutes

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
    default:
      return {
        background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
        color: 'var(--accent-yellow)',
        border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
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

function TableSkeleton() {
  return (
    <div style={{ padding: '16px' }}>
      {[...Array(5)].map((_, i) => (
        <Skeleton key={i} className="h-10 w-full mb-2" />
      ))}
    </div>
  )
}

function SeverityChip({ label, count, severity }: { label: string; count: number; severity: string }) {
  return <span style={chipStyle(severity)}>{label}: {count}</span>
}

function SummaryBar({ summary }: { summary: AuditSummary }) {
  return (
    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
      <SeverityChip label="Critical" count={summary.critical} severity="critical" />
      <SeverityChip label="High" count={summary.high} severity="high" />
      <SeverityChip label="Medium" count={summary.medium} severity="medium" />
      <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginLeft: 4 }}>
        {summary.total} total findings
      </span>
    </div>
  )
}

function IssueTypeBadge({ issueType }: { issueType: string }) {
  const label = issueType.replace(/_/g, ' ')
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '4px',
        fontSize: '0.75rem',
        fontWeight: 500,
        background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
        color: 'var(--accent-blue)',
        textTransform: 'capitalize',
      }}
    >
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Rules sub-view
// ---------------------------------------------------------------------------

function RulesTable({ rules, loading }: { rules: FirewallRule[]; loading: boolean }) {
  if (loading) return <TableSkeleton />
  if (rules.length === 0) {
    return (
      <div
        style={{
          padding: '40px',
          textAlign: 'center',
          color: 'var(--text-secondary)',
          fontSize: '0.9rem',
        }}
      >
        <Flame size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
        No Azure Firewalls found across monitored subscriptions.
      </div>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Firewall</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Policy</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Collection</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Rule Name</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Type</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Source</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Destination</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Ports</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rules.map((r, idx) => (
          <TableRow key={`${r.firewall_id}-${r.rule_name}-${idx}`} style={{ borderBottom: '1px solid var(--border)' }}>
            <TableCell>
              <div style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: '0.875rem' }}>
                {r.firewall_name || '—'}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                {r.resource_group}
              </div>
            </TableCell>
            <TableCell style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              {r.policy_name || '—'}
            </TableCell>
            <TableCell>
              <div style={{ color: 'var(--text-primary)', fontSize: '0.875rem' }}>
                {r.collection_name || '—'}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                Priority {r.collection_priority}
              </div>
            </TableCell>
            <TableCell style={{ color: 'var(--text-primary)', fontSize: '0.875rem' }}>
              {r.rule_name}
            </TableCell>
            <TableCell style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
              {r.rule_type || '—'}
            </TableCell>
            <TableCell>
              <code
                style={{
                  fontSize: '0.75rem',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: 'color-mix(in srgb, var(--border) 50%, transparent)',
                  color: 'var(--text-primary)',
                }}
              >
                {r.source_addresses.join(', ') || '*'}
              </code>
            </TableCell>
            <TableCell>
              <code
                style={{
                  fontSize: '0.75rem',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: 'color-mix(in srgb, var(--border) 50%, transparent)',
                  color: 'var(--text-primary)',
                }}
              >
                {r.destination_addresses.join(', ') || '*'}
              </code>
            </TableCell>
            <TableCell>
              <code
                style={{
                  fontSize: '0.75rem',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
                  color: 'var(--accent-blue)',
                }}
              >
                {r.destination_ports.join(', ') || '*'}
              </code>
            </TableCell>
            <TableCell>
              <Badge
                style={{
                  background:
                    r.action?.toLowerCase() === 'allow'
                      ? 'color-mix(in srgb, var(--accent-green, #22c55e) 15%, transparent)'
                      : 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                  color:
                    r.action?.toLowerCase() === 'allow'
                      ? 'var(--accent-green, #22c55e)'
                      : 'var(--accent-red)',
                  fontWeight: 600,
                  fontSize: '0.75rem',
                  textTransform: 'capitalize',
                }}
              >
                {r.action || '—'}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// ---------------------------------------------------------------------------
// Audit sub-view
// ---------------------------------------------------------------------------

function AuditTable({ findings, loading }: { findings: FirewallAuditFinding[]; loading: boolean }) {
  if (loading) return <TableSkeleton />
  if (findings.length === 0) {
    return (
      <div
        style={{
          padding: '40px',
          textAlign: 'center',
          color: 'var(--text-secondary)',
          fontSize: '0.9rem',
        }}
      >
        <Flame size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
        No Azure Firewall audit findings found across monitored subscriptions.
      </div>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Severity</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Firewall</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Rule</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Issue</TableHead>
          <TableHead style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Remediation</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {findings.map((f, idx) => (
          <TableRow key={`${f.firewall_name}-${f.rule_name}-${f.issue_type}-${idx}`} style={{ borderBottom: '1px solid var(--border)' }}>
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
            <TableCell>
              <div style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: '0.875rem' }}>
                {f.firewall_name}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                {f.collection_name}
              </div>
            </TableCell>
            <TableCell style={{ color: 'var(--text-primary)', fontSize: '0.875rem' }}>
              {f.rule_name}
            </TableCell>
            <TableCell>
              <IssueTypeBadge issueType={f.issue_type} />
              <div
                style={{
                  marginTop: 4,
                  color: 'var(--text-secondary)',
                  fontSize: '0.75rem',
                  maxWidth: '280px',
                }}
              >
                {f.detail}
              </div>
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
                  <p style={{ marginBottom: 8, color: 'var(--text-secondary)' }}>{f.detail}</p>
                  <p style={{ fontWeight: 500 }}>Remediation</p>
                  <p style={{ color: 'var(--text-secondary)' }}>{f.remediation}</p>
                </TooltipContent>
              </Tooltip>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function FirewallTab({ subscriptions = [] }: FirewallTabProps) {
  type View = 'rules' | 'audit'
  const [view, setView] = useState<View>('rules')

  const [rules, setRules] = useState<FirewallRule[]>([])
  const [findings, setFindings] = useState<FirewallAuditFinding[]>([])
  const [auditSummary, setAuditSummary] = useState<AuditSummary | null>(null)
  const [auditGeneratedAt, setAuditGeneratedAt] = useState<string | null>(null)

  const [loadingRules, setLoadingRules] = useState(false)
  const [loadingAudit, setLoadingAudit] = useState(false)
  const [errorRules, setErrorRules] = useState<string | null>(null)
  const [errorAudit, setErrorAudit] = useState<string | null>(null)

  const [severityFilter, setSeverityFilter] = useState<string>('all')

  const fetchRules = useCallback(async () => {
    setLoadingRules(true)
    setErrorRules(null)
    try {
      const params = new URLSearchParams()
      if (subscriptions.length > 0) params.set('subscription_ids', subscriptions.join(','))
      const url = `/api/proxy/firewall/rules${params.toString() ? `?${params}` : ''}`
      const res = await fetch(url, { cache: 'no-store' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.error ?? `HTTP ${res.status}`)
      }
      const data: RulesResponse = await res.json()
      setRules(data.rules ?? [])
    } catch (err: unknown) {
      setErrorRules(err instanceof Error ? err.message : 'Failed to load firewall rules')
    } finally {
      setLoadingRules(false)
    }
  }, [subscriptions])

  const fetchAudit = useCallback(async () => {
    setLoadingAudit(true)
    setErrorAudit(null)
    try {
      const params = new URLSearchParams()
      if (subscriptions.length > 0) params.set('subscription_ids', subscriptions.join(','))
      if (severityFilter !== 'all') params.set('severity', severityFilter)
      const url = `/api/proxy/firewall/audit${params.toString() ? `?${params}` : ''}`
      const res = await fetch(url, { cache: 'no-store' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.error ?? `HTTP ${res.status}`)
      }
      const data: AuditResponse = await res.json()
      setFindings(data.findings ?? [])
      setAuditSummary(data.summary ?? null)
      setAuditGeneratedAt(data.generated_at ?? null)
    } catch (err: unknown) {
      setErrorAudit(err instanceof Error ? err.message : 'Failed to load firewall audit')
    } finally {
      setLoadingAudit(false)
    }
  }, [subscriptions, severityFilter])

  // Load on mount and poll
  useEffect(() => {
    fetchRules()
    fetchAudit()
  }, [fetchRules, fetchAudit])

  useEffect(() => {
    const id = setInterval(() => {
      fetchRules()
      fetchAudit()
    }, REFRESH_INTERVAL_MS)
    return () => clearInterval(id)
  }, [fetchRules, fetchAudit])

  const loading = view === 'rules' ? loadingRules : loadingAudit
  const error = view === 'rules' ? errorRules : errorAudit

  return (
    <TooltipProvider>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Flame size={20} style={{ color: 'var(--accent-blue)' }} />
            <h2
              style={{
                fontSize: '1.1rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                margin: 0,
              }}
            >
              Azure Firewall
            </h2>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => { fetchRules(); fetchAudit() }}
              disabled={loadingRules || loadingAudit}
              style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
            >
              <RefreshCw
                size={14}
                className={loadingRules || loadingAudit ? 'animate-spin' : ''}
                style={{ marginRight: 4 }}
              />
              Refresh
            </Button>
          </div>
        </div>

        {/* View toggle */}
        <div
          style={{
            display: 'inline-flex',
            gap: '4px',
            padding: '4px',
            borderRadius: '8px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            width: 'fit-content',
          }}
        >
          {(['rules', 'audit'] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              style={{
                padding: '6px 18px',
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer',
                fontSize: '0.875rem',
                fontWeight: 500,
                transition: 'all 0.15s',
                background: view === v ? 'var(--accent-blue)' : 'transparent',
                color: view === v ? '#fff' : 'var(--text-secondary)',
              }}
            >
              {v.charAt(0).toUpperCase() + v.slice(1)}
            </button>
          ))}
        </div>

        {/* Audit summary bar */}
        {view === 'audit' && auditSummary && <SummaryBar summary={auditSummary} />}

        {/* Audit severity filter */}
        {view === 'audit' && (
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
          </div>
        )}

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

        {/* Table */}
        <div
          style={{
            borderRadius: '8px',
            border: '1px solid var(--border)',
            overflow: 'hidden',
            background: 'var(--bg-surface)',
          }}
        >
          {view === 'rules' ? (
            <RulesTable rules={rules} loading={loadingRules} />
          ) : (
            <AuditTable findings={findings} loading={loadingAudit} />
          )}
        </div>

        {/* Footer row count */}
        {!loading && (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
            {view === 'rules'
              ? `Showing ${rules.length} rule${rules.length !== 1 ? 's' : ''}`
              : `Showing ${findings.length} finding${findings.length !== 1 ? 's' : ''}`}
            {view === 'audit' && auditGeneratedAt && (
              <> · Generated {new Date(auditGeneratedAt).toLocaleString()}</>
            )}
          </div>
        )}
      </div>
    </TooltipProvider>
  )
}

export default FirewallTab
