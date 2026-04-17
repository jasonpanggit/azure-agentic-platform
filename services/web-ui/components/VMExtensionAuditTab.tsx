'use client'

import { useState, useEffect, useCallback } from 'react'
import { HardDrive, RefreshCw, AlertTriangle, CheckCircle, ShieldAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ExtensionFinding {
  readonly finding_id: string
  readonly vm_name: string
  readonly resource_group: string
  readonly subscription_id: string
  readonly location: string
  readonly os_type: string
  readonly severity: 'critical' | 'high' | 'medium' | 'info' | 'compliant'
  readonly compliance_score: number
  readonly installed_extensions: readonly { name: string; publisher: string; state: string }[]
  readonly missing_extensions: readonly { name: string; description: string }[]
  readonly failed_extensions: readonly { name: string; state: string }[]
  readonly scanned_at: string
}

interface ExtensionSummary {
  readonly total_vms: number
  readonly compliant: number
  readonly critical: number
  readonly high: number
  readonly medium: number
  readonly info: number
  readonly coverage_pct: number
  readonly top_missing: readonly { name: string; count: number }[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function severityColor(severity: string): string {
  switch (severity) {
    case 'critical':  return 'var(--accent-red)'
    case 'high':      return 'var(--accent-orange)'
    case 'medium':    return 'var(--accent-yellow)'
    case 'info':      return 'var(--accent-blue)'
    case 'compliant': return 'var(--accent-green)'
    default:          return 'var(--text-muted)'
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = severityColor(severity)
  return (
    <Badge
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 40%, transparent)`,
      }}
    >
      {severity.toUpperCase()}
    </Badge>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function VMExtensionAuditTab({ subscriptionId }: { subscriptionId?: string }) {
  const [summary, setSummary] = useState<ExtensionSummary | null>(null)
  const [findings, setFindings] = useState<ExtensionFinding[]>([])
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [osFilter, setOsFilter] = useState<string>('ALL')
  const [severityFilter, setSeverityFilter] = useState<string>('ALL')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (subscriptionId) params.set('subscription_id', subscriptionId)
      if (severityFilter !== 'ALL') params.set('severity', severityFilter.toLowerCase())

      const [summaryRes, findingsRes] = await Promise.all([
        fetch('/api/proxy/vm-extensions/summary'),
        fetch(`/api/proxy/vm-extensions?${params}`),
      ])

      if (summaryRes.ok) {
        setSummary(await summaryRes.json())
      }
      if (findingsRes.ok) {
        const data = await findingsRes.json()
        setFindings(data.findings ?? [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load extension data')
    } finally {
      setLoading(false)
    }
  }, [subscriptionId, severityFilter])

  useEffect(() => {
    void fetchData()
    const id = setInterval(() => { void fetchData() }, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      const params = new URLSearchParams()
      if (subscriptionId) params.set('subscription_id', subscriptionId)
      await fetch(`/api/proxy/vm-extensions/scan?${params}`, { method: 'POST' })
      await fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const filteredFindings = findings.filter((f) => {
    const osMatch = osFilter === 'ALL' || f.os_type.toLowerCase() === osFilter.toLowerCase()
    return osMatch
  })

  return (
    <div className="flex flex-col gap-6 p-4" style={{ color: 'var(--text-primary)' }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HardDrive className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-lg font-semibold">VM Extension Health Audit</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchData()}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => void handleScan()} disabled={scanning}>
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {error && (
        <div
          className="rounded p-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          {error}
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { label: 'Total VMs',  value: summary.total_vms,  color: 'var(--text-primary)' },
            { label: 'Compliant',  value: summary.compliant,  color: 'var(--accent-green)' },
            { label: 'Critical',   value: summary.critical,   color: 'var(--accent-red)' },
            { label: 'High',       value: summary.high,       color: 'var(--accent-orange)' },
            { label: 'Medium',     value: summary.medium,     color: 'var(--accent-yellow)' },
          ].map(({ label, value, color }) => (
            <div
              key={label}
              className="rounded-lg border p-3 text-center"
              style={{ borderColor: 'var(--border)', background: 'var(--bg-canvas)' }}
            >
              <div className="text-2xl font-bold" style={{ color }}>{value}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Coverage progress bar */}
      {summary && (
        <div className="space-y-1">
          <div className="flex justify-between text-sm">
            <span style={{ color: 'var(--text-muted)' }}>Compliance Coverage</span>
            <span style={{ color: summary.coverage_pct >= 80 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
              {summary.coverage_pct}%
            </span>
          </div>
          <div style={{ background: 'var(--border)', borderRadius: '4px', height: '8px', overflow: 'hidden' }}>
            <div style={{ width: `${summary.coverage_pct}%`, height: '100%', background: summary.coverage_pct >= 80 ? 'var(--accent-green)' : 'var(--accent-red)', transition: 'width 0.3s' }} />
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <Select value={osFilter} onValueChange={setOsFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="OS Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All OS Types</SelectItem>
            <SelectItem value="Windows">Windows</SelectItem>
            <SelectItem value="Linux">Linux</SelectItem>
          </SelectContent>
        </Select>

        <Select value={severityFilter} onValueChange={setSeverityFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All Severities</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="medium">Medium</SelectItem>
            <SelectItem value="info">Info</SelectItem>
            <SelectItem value="compliant">Compliant</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Findings table */}
      <div className="rounded-lg border overflow-auto" style={{ borderColor: 'var(--border)' }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>VM Name</TableHead>
              <TableHead>OS</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Missing Extensions</TableHead>
              <TableHead>Failed Extensions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8" style={{ color: 'var(--text-muted)' }}>
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {!loading && filteredFindings.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8" style={{ color: 'var(--text-muted)' }}>
                  No findings found. Run a scan to populate data.
                </TableCell>
              </TableRow>
            )}
            {filteredFindings.map((f) => (
              <TableRow key={f.finding_id}>
                <TableCell className="font-medium">{f.vm_name}</TableCell>
                <TableCell>
                  <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{f.os_type}</span>
                </TableCell>
                <TableCell>
                  <SeverityBadge severity={f.severity} />
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {f.missing_extensions.length === 0 ? (
                      <span className="text-xs" style={{ color: 'var(--accent-green)' }}>None</span>
                    ) : (
                      f.missing_extensions.map((m) => (
                        <Badge
                          key={m.name}
                          variant="outline"
                          className="text-xs"
                          style={{ color: 'var(--accent-orange)' }}
                        >
                          {m.name}
                        </Badge>
                      ))
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {f.failed_extensions.length === 0 ? (
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>—</span>
                    ) : (
                      f.failed_extensions.map((fe) => (
                        <Badge
                          key={fe.name}
                          variant="outline"
                          className="text-xs"
                          style={{ color: 'var(--accent-red)' }}
                        >
                          {fe.name} ({fe.state})
                        </Badge>
                      ))
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Top missing */}
      {summary && summary.top_missing.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-muted)' }}>
            Most Frequently Missing Extensions
          </h3>
          <div className="flex flex-wrap gap-2">
            {summary.top_missing.map((m) => (
              <div
                key={m.name}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs"
                style={{
                  background: 'color-mix(in srgb, var(--accent-orange) 10%, transparent)',
                  color: 'var(--accent-orange)',
                }}
              >
                <AlertTriangle className="h-3 w-3" />
                {m.name} ({m.count} VMs)
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
