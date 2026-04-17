'use client'

import { useEffect, useState, useCallback } from 'react'
import { Network, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface LBFinding {
  id: string
  subscription_id: string
  resource_group: string
  lb_name: string
  sku: string
  location: string
  frontend_count: number
  backend_count: number
  probe_count: number
  rule_count: number
  provisioning_state: string
  findings: string[]
  severity: string
  scanned_at: string
}

interface LBSummary {
  total: number
  by_severity: Record<string, number>
  basic_sku_count: number
}

function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase()
  const style: React.CSSProperties =
    s === 'critical'
      ? { background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)', border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)' }
      : s === 'high'
      ? { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)', border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)' }
      : s === 'medium'
      ? { background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)', color: 'var(--accent-yellow)', border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)' }
      : { background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)', color: 'var(--accent-blue)', border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)' }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase" style={style}>
      {severity}
    </span>
  )
}

function SkuBadge({ sku }: { sku: string }) {
  const isBasic = sku.toLowerCase() === 'basic'
  const style: React.CSSProperties = isBasic
    ? { background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)', color: 'var(--accent-yellow)', border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)' }
    : { background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)', color: 'var(--accent-blue)', border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)' }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium" style={style}>
      {sku || '—'}
    </span>
  )
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div
      className="rounded-lg px-4 py-3 flex flex-col gap-0.5 min-w-[110px]"
      style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
    >
      <span className="text-[22px] font-bold" style={{ color: color ?? 'var(--text-primary)' }}>
        {value}
      </span>
      <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

export function LBHealthTab() {
  const [findings, setFindings] = useState<LBFinding[]>([])
  const [summary, setSummary] = useState<LBSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (severityFilter) params.set('severity', severityFilter)

      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/network/lb${params.toString() ? `?${params}` : ''}`),
        fetch('/api/proxy/network/lb/summary'),
      ])

      if (findingsRes.ok) {
        const data = await findingsRes.json()
        setFindings(Array.isArray(data) ? data : [])
      }
      if (summaryRes.ok) {
        const data = await summaryRes.json()
        setSummary(data)
      }
    } catch {
      // Network errors handled silently
    } finally {
      setLoading(false)
    }
  }, [severityFilter])

  useEffect(() => {
    void fetchData()
  }, [fetchData])

  const handleScan = async () => {
    setScanning(true)
    try {
      await fetch('/api/proxy/network/lb/scan', { method: 'POST' })
      await fetchData()
    } catch {
      // Scan errors handled silently
    } finally {
      setScanning(false)
    }
  }

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const severities = ['', 'critical', 'high', 'medium', 'info']

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="flex flex-wrap gap-3">
        <StatCard label="Total LBs" value={summary?.total ?? 0} />
        <StatCard label="Critical" value={summary?.by_severity?.critical ?? 0} color="var(--accent-red)" />
        <StatCard label="High" value={summary?.by_severity?.high ?? 0} color="var(--accent-orange)" />
        <StatCard label="Medium" value={summary?.by_severity?.medium ?? 0} color="var(--accent-yellow)" />
        <StatCard label="Basic SKU" value={summary?.basic_sku_count ?? 0} color="var(--accent-yellow)" />
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="text-sm rounded px-2 py-1"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          {severities.map((s) => (
            <option key={s} value={s}>
              {s === '' ? 'All Severities' : s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          size="sm"
          onClick={handleScan}
          disabled={scanning || loading}
          className="flex items-center gap-1.5"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-label="Scan" />
          {scanning ? 'Scanning…' : 'Scan Now'}
        </Button>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ color: 'var(--text-secondary)' }} className="text-sm py-8 text-center">
          Loading load balancer findings…
        </div>
      ) : findings.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)' }} className="text-sm py-8 text-center">
          No load balancer findings. Run a scan to populate data.
        </div>
      ) : (
        <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead style={{ width: 28 }} />
                <TableHead>LB Name</TableHead>
                <TableHead>SKU</TableHead>
                <TableHead>Location</TableHead>
                <TableHead className="text-right">Backends</TableHead>
                <TableHead className="text-right">Probes</TableHead>
                <TableHead className="text-right">Rules</TableHead>
                <TableHead className="text-right">Findings</TableHead>
                <TableHead>Severity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {findings.map((f) => {
                const expanded = expandedIds.has(f.id)
                return (
                  <>
                    <TableRow
                      key={f.id}
                      onClick={() => f.findings.length > 0 && toggleExpand(f.id)}
                      style={{ cursor: f.findings.length > 0 ? 'pointer' : 'default' }}
                    >
                      <TableCell>
                        {f.findings.length > 0 ? (
                          expanded
                            ? <ChevronDown className="h-3.5 w-3.5" style={{ color: 'var(--text-secondary)' }} aria-label="Collapse" />
                            : <ChevronRight className="h-3.5 w-3.5" style={{ color: 'var(--text-secondary)' }} aria-label="Expand" />
                        ) : null}
                      </TableCell>
                      <TableCell className="font-medium" style={{ color: 'var(--text-primary)' }}>
                        {f.lb_name}
                        <div className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                          {f.resource_group}
                        </div>
                      </TableCell>
                      <TableCell><SkuBadge sku={f.sku} /></TableCell>
                      <TableCell style={{ color: 'var(--text-secondary)' }}>{f.location}</TableCell>
                      <TableCell className="text-right" style={{ color: f.backend_count === 0 ? 'var(--accent-red)' : 'var(--text-primary)', fontWeight: f.backend_count === 0 ? 700 : 400 }}>
                        {f.backend_count}
                      </TableCell>
                      <TableCell className="text-right" style={{ color: f.probe_count === 0 ? 'var(--accent-orange)' : 'var(--text-primary)', fontWeight: f.probe_count === 0 ? 700 : 400 }}>
                        {f.probe_count}
                      </TableCell>
                      <TableCell className="text-right" style={{ color: f.rule_count === 0 ? 'var(--accent-orange)' : 'var(--text-primary)', fontWeight: f.rule_count === 0 ? 700 : 400 }}>
                        {f.rule_count}
                      </TableCell>
                      <TableCell className="text-right" style={{ color: 'var(--text-secondary)' }}>
                        {f.findings.length}
                      </TableCell>
                      <TableCell><SeverityBadge severity={f.severity} /></TableCell>
                    </TableRow>
                    {expanded && f.findings.length > 0 && (
                      <TableRow key={`${f.id}-findings`}>
                        <TableCell colSpan={9} style={{ background: 'var(--bg-subtle)', paddingLeft: '2.5rem' }}>
                          <ul className="space-y-1 py-1">
                            {f.findings.map((finding, i) => (
                              <li key={i} className="text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                                • {finding}
                              </li>
                            ))}
                          </ul>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
