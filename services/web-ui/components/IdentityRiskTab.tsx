'use client'

import { useEffect, useState, useCallback } from 'react'
import { Key, RefreshCw, AlertTriangle, Info } from 'lucide-react'
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

interface CredentialRisk {
  risk_id: string
  service_principal_id: string
  service_principal_name: string
  credential_type: string
  credential_name: string
  expiry_date: string
  days_until_expiry: number
  severity: string
  detected_at: string
}

interface IdentitySummary {
  total_sps_checked: number
  critical_count: number
  high_count: number
  medium_count: number
  expired_count: number
  expiring_30d_count: number
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000 // 10 minutes

function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase()
  const style: React.CSSProperties =
    s === 'critical'
      ? { background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)', color: 'var(--accent-red)', border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)' }
      : s === 'high'
      ? { background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)', color: 'var(--accent-orange)', border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)' }
      : { background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)', color: 'var(--accent-yellow)', border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)' }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase" style={style}>
      {severity}
    </span>
  )
}

function DaysCell({ days }: { days: number }) {
  const color =
    days < 0
      ? 'var(--accent-red)'
      : days <= 30
      ? 'var(--accent-orange)'
      : 'var(--accent-yellow)'
  const label = days < 0 ? `${Math.abs(days)}d ago` : `${days}d`
  return <span style={{ color, fontWeight: 600 }}>{label}</span>
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color?: string
}) {
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

export function IdentityRiskTab() {
  const [risks, setRisks] = useState<CredentialRisk[]>([])
  const [summary, setSummary] = useState<IdentitySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [graphUnavailable, setGraphUnavailable] = useState(false)
  const [severityFilter, setSeverityFilter] = useState<string>('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [risksRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/identity-risks${severityFilter ? `?severity=${severityFilter}` : ''}`),
        fetch('/api/proxy/identity-risks/summary'),
      ])

      if (risksRes.ok) {
        const data = await risksRes.json()
        setRisks(data.risks ?? [])
        // If no risks and scan hasn't been triggered yet, Graph may not be configured
        setGraphUnavailable(false)
      }
      if (summaryRes.ok) {
        const data = await summaryRes.json()
        setSummary(data)
      }
    } catch {
      // Network errors handled silently; UI shows stale data
    } finally {
      setLoading(false)
    }
  }, [severityFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  const filteredRisks = severityFilter
    ? risks.filter((r) => r.severity.toLowerCase() === severityFilter.toLowerCase())
    : risks

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-[15px] font-semibold" style={{ color: 'var(--text-primary)' }}>
            Identity Risk — Credential Expiry
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="text-[12px] rounded px-2 py-1.5 outline-none"
            style={{
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchData()}
            disabled={loading}
            className="gap-1.5 text-[12px]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Graph unavailable banner */}
      {graphUnavailable && (
        <div
          className="flex items-center gap-2 rounded-lg px-4 py-3 text-[13px]"
          style={{
            background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
            color: 'var(--text-primary)',
          }}
        >
          <Info className="h-4 w-4 shrink-0" style={{ color: 'var(--accent-blue)' }} />
          Microsoft Graph API not configured — credential expiry data unavailable. Grant the
          managed identity <code className="font-mono text-[11px]">Application.Read.All</code> on
          Microsoft Graph to enable this feature.
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="flex flex-wrap gap-3">
          <StatCard label="SPs Checked" value={summary.total_sps_checked} />
          <StatCard label="Expired" value={summary.expired_count} color="var(--accent-red)" />
          <StatCard label="Expiring 30d" value={summary.expiring_30d_count} color="var(--accent-orange)" />
          <StatCard label="Expiring 90d" value={summary.medium_count} color="var(--accent-yellow)" />
          <StatCard label="Critical" value={summary.critical_count} color="var(--accent-red)" />
          <StatCard label="High" value={summary.high_count} color="var(--accent-orange)" />
        </div>
      )}

      {/* Risk table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        {loading ? (
          <div className="p-8 text-center text-[13px]" style={{ color: 'var(--text-secondary)' }}>
            Loading credential risks…
          </div>
        ) : filteredRisks.length === 0 ? (
          <div className="p-8 text-center text-[13px]" style={{ color: 'var(--text-secondary)' }}>
            No identity risk findings found.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Service Principal</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>Expiry Date</TableHead>
                <TableHead>Days Until Expiry</TableHead>
                <TableHead>Severity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredRisks.map((risk) => (
                <TableRow key={risk.risk_id}>
                  <TableCell className="font-medium text-[13px]">
                    {risk.service_principal_name}
                  </TableCell>
                  <TableCell>
                    <span
                      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium"
                      style={{
                        background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                        color: 'var(--accent-blue)',
                        border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)',
                      }}
                    >
                      {risk.credential_type}
                    </span>
                  </TableCell>
                  <TableCell className="text-[13px]" style={{ color: 'var(--text-secondary)' }}>
                    {risk.credential_name}
                  </TableCell>
                  <TableCell className="text-[13px]" style={{ color: 'var(--text-secondary)' }}>
                    {risk.expiry_date ? new Date(risk.expiry_date).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell>
                    <DaysCell days={risk.days_until_expiry} />
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={risk.severity} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
