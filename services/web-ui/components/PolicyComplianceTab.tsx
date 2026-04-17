'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { RefreshCw, Download } from 'lucide-react'

interface PolicyViolation {
  violation_id: string
  subscription_id: string
  resource_id: string
  resource_name: string
  resource_type: string
  resource_group: string
  policy_definition_id: string
  policy_name: string
  policy_display_name: string
  initiative_name: string
  effect: string
  severity: 'high' | 'medium' | 'low'
  timestamp: string
  captured_at: string
}

interface PolicySummary {
  total_violations: number
  by_severity: { high: number; medium: number; low: number }
  top_violated_policies: Array<{ policy_name: string; count: number }>
  top_affected_subscriptions: Array<{ subscription_id: string; count: number }>
}

interface PolicyComplianceTabProps {
  subscriptions?: string[]
}

type GroupBy = 'policy' | 'resource'

const SEVERITY_COLORS: Record<string, string> = {
  high: 'var(--accent-red)',
  medium: 'var(--accent-yellow)',
  low: 'var(--accent-blue)',
}

const SEVERITY_BG: Record<string, string> = {
  high: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
  medium: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
  low: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
}

const EFFECT_COLORS: Record<string, string> = {
  deny: 'var(--accent-red)',
  audit: 'var(--accent-yellow)',
  auditifnotexists: 'var(--accent-yellow)',
  deployifnotexists: 'var(--accent-blue)',
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        color: SEVERITY_COLORS[severity] ?? 'var(--text-primary)',
        background: SEVERITY_BG[severity] ?? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
      }}
    >
      {severity}
    </span>
  )
}

function EffectChip({ effect }: { effect: string }) {
  const key = effect.toLowerCase()
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono"
      style={{
        color: EFFECT_COLORS[key] ?? 'var(--text-secondary)',
        background: 'color-mix(in srgb, var(--border) 40%, transparent)',
      }}
    >
      {effect}
    </span>
  )
}

function SummaryStrip({ summary, loading }: { summary: PolicySummary | null; loading: boolean }) {
  const items = [
    { label: 'Total Violations', value: summary?.total_violations ?? 0, color: 'var(--text-primary)' },
    { label: 'High (Deny)', value: summary?.by_severity.high ?? 0, color: 'var(--accent-red)' },
    { label: 'Medium (Audit)', value: summary?.by_severity.medium ?? 0, color: 'var(--accent-yellow)' },
    { label: 'Low', value: summary?.by_severity.low ?? 0, color: 'var(--accent-blue)' },
    {
      label: 'Top Policy',
      value: summary?.top_violated_policies?.[0]?.policy_name?.split(' ').slice(0, 3).join(' ') ?? '—',
      color: 'var(--text-primary)',
      small: true,
    },
  ]

  return (
    <div className="grid grid-cols-5 gap-3 mb-6">
      {items.map(({ label, value, color, small }) => (
        <Card key={label} style={{ border: '1px solid var(--border)' }}>
          <CardContent className="p-4">
            {loading ? (
              <Skeleton className="h-8 w-full" />
            ) : (
              <>
                <div
                  className={`font-bold ${small ? 'text-sm truncate' : 'text-2xl'}`}
                  style={{ color }}
                  title={String(value)}
                >
                  {value}
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{label}</div>
              </>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function downloadCsv(violations: PolicyViolation[]) {
  const headers = [
    'Resource', 'Type', 'Resource Group', 'Subscription', 'Policy', 'Effect', 'Severity', 'Timestamp',
  ]
  const rows = violations.map((v) => [
    v.resource_name,
    v.resource_type,
    v.resource_group,
    v.subscription_id,
    v.policy_display_name || v.policy_name,
    v.effect,
    v.severity,
    v.timestamp,
  ])
  const csv = [headers, ...rows]
    .map((row) => row.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `policy-violations-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function groupByPolicy(violations: PolicyViolation[]): Array<{ key: string; violations: PolicyViolation[] }> {
  const map = new Map<string, PolicyViolation[]>()
  for (const v of violations) {
    const key = v.policy_display_name || v.policy_name || 'Unknown'
    const existing = map.get(key) ?? []
    map.set(key, [...existing, v])
  }
  return Array.from(map.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .map(([key, vs]) => ({ key, violations: vs }))
}

export function PolicyComplianceTab({ subscriptions = [] }: PolicyComplianceTabProps) {
  const [violations, setViolations] = useState<PolicyViolation[]>([])
  const [summary, setSummary] = useState<PolicySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [groupBy, setGroupBy] = useState<GroupBy>('resource')
  const [filterSub, setFilterSub] = useState<string>('all')
  const [filterSeverity, setFilterSeverity] = useState<string>('all')
  const [policySearch, setPolicySearch] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterSub !== 'all') params.set('subscription_id', filterSub)
      if (filterSeverity !== 'all') params.set('severity', filterSeverity)
      if (policySearch.trim()) params.set('policy_name', policySearch.trim())
      const qs = params.toString() ? `?${params.toString()}` : ''

      const [vRes, sRes] = await Promise.all([
        fetch(`/api/proxy/policy/violations${qs}`),
        fetch('/api/proxy/policy/summary'),
      ])
      if (vRes.ok) {
        const data = await vRes.json()
        setViolations(data.violations ?? [])
      }
      if (sRes.ok) {
        const data = await sRes.json()
        setSummary(data)
      }
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [filterSub, filterSeverity, policySearch])

  useEffect(() => {
    void fetchData()
    const interval = setInterval(() => { void fetchData() }, 10 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      await fetch('/api/proxy/policy/scan', { method: 'POST' })
      setTimeout(() => { void fetchData() }, 3000)
    } finally {
      setTimeout(() => setScanning(false), 3000)
    }
  }

  const uniqueSubs = Array.from(new Set(violations.map((v) => v.subscription_id)))
  const grouped = groupBy === 'policy' ? groupByPolicy(violations) : null

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Policy Compliance
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            Non-compliant Azure Policy states across all subscriptions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => downloadCsv(violations)}
            disabled={violations.length === 0}
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <Download className="h-4 w-4 mr-1" />
            Export CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchData()}
            disabled={loading}
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={() => void handleScan()}
            disabled={scanning}
            style={{ background: 'var(--accent-blue)', color: '#fff' }}
          >
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {/* Summary strip */}
      <SummaryStrip summary={summary} loading={loading} />

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={filterSub} onValueChange={setFilterSub}>
          <SelectTrigger className="w-48 text-sm" style={{ borderColor: 'var(--border)' }}>
            <SelectValue placeholder="All subscriptions" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All subscriptions</SelectItem>
            {uniqueSubs.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={filterSeverity} onValueChange={setFilterSeverity}>
          <SelectTrigger className="w-36 text-sm" style={{ borderColor: 'var(--border)' }}>
            <SelectValue placeholder="All severities" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All severities</SelectItem>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="medium">Medium</SelectItem>
            <SelectItem value="low">Low</SelectItem>
          </SelectContent>
        </Select>

        <Input
          className="w-56 text-sm"
          placeholder="Search policy name…"
          value={policySearch}
          onChange={(e) => setPolicySearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void fetchData() }}
          style={{ borderColor: 'var(--border)' }}
        />

        {/* Group-by toggle */}
        <div
          className="flex items-center rounded overflow-hidden text-xs"
          style={{ border: '1px solid var(--border)' }}
        >
          {(['resource', 'policy'] as GroupBy[]).map((g) => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className="px-3 py-1.5 capitalize transition-colors"
              style={{
                background: groupBy === g ? 'var(--accent-blue)' : 'transparent',
                color: groupBy === g ? '#fff' : 'var(--text-secondary)',
              }}
            >
              By {g}
            </button>
          ))}
        </div>

        <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          {violations.length} violation{violations.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : violations.length === 0 ? (
        <div
          className="rounded-lg p-8 text-center text-sm"
          style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
        >
          No policy violations found. Run a scan to populate data.
        </div>
      ) : groupBy === 'policy' && grouped ? (
        <div className="space-y-4">
          {grouped.map(({ key, violations: groupViolations }) => (
            <div key={key} className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
              <div
                className="px-4 py-2 flex items-center justify-between text-sm font-medium"
                style={{ background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)' }}
              >
                <span style={{ color: 'var(--text-primary)' }}>{key}</span>
                <span
                  className="text-xs px-2 py-0.5 rounded"
                  style={{
                    background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                    color: 'var(--accent-red)',
                  }}
                >
                  {groupViolations.length} affected
                </span>
              </div>
              <ViolationsTable violations={groupViolations} />
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          <ViolationsTable violations={violations} />
        </div>
      )}
    </div>
  )
}

function ViolationsTable({ violations }: { violations: PolicyViolation[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow style={{ background: 'var(--bg-subtle)' }}>
          <TableHead className="text-xs">Resource</TableHead>
          <TableHead className="text-xs">Type</TableHead>
          <TableHead className="text-xs">Policy</TableHead>
          <TableHead className="text-xs">Effect</TableHead>
          <TableHead className="text-xs">Severity</TableHead>
          <TableHead className="text-xs">Timestamp</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {violations.map((v) => (
          <TableRow key={v.violation_id}>
            <TableCell className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>
              <div>{v.resource_name}</div>
              <div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{v.resource_group}</div>
            </TableCell>
            <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {v.resource_type}
            </TableCell>
            <TableCell className="text-xs" style={{ color: 'var(--text-primary)', maxWidth: 260 }}>
              <div className="truncate" title={v.policy_display_name || v.policy_name}>
                {v.policy_display_name || v.policy_name}
              </div>
              {v.initiative_name && (
                <div className="text-[10px] truncate" style={{ color: 'var(--text-secondary)' }}>
                  {v.initiative_name}
                </div>
              )}
            </TableCell>
            <TableCell className="text-xs"><EffectChip effect={v.effect} /></TableCell>
            <TableCell className="text-xs"><SeverityBadge severity={v.severity} /></TableCell>
            <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {v.timestamp ? new Date(v.timestamp).toLocaleDateString() : '—'}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
