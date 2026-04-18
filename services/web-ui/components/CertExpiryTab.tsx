'use client'

import { useEffect, useState, useCallback } from 'react'
import { ShieldCheck } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface CertFinding {
  id: string
  subscription_id: string
  resource_group: string
  cert_name: string
  cert_type: string
  vault_or_app_name: string
  expires_on: string
  days_until_expiry: number
  severity: string
  scanned_at: string
}

interface CertSummary {
  total: number
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  soonest_expiry: string | null
  soonest_expiry_days: number | null
}

const REFRESH_INTERVAL_MS = 10 * 60 * 1000

function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase()
  const style: React.CSSProperties =
    s === 'critical'
      ? {
          background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
          color: 'var(--accent-red)',
          border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
        }
      : s === 'high'
      ? {
          background: 'color-mix(in srgb, var(--accent-orange) 15%, transparent)',
          color: 'var(--accent-orange)',
          border: '1px solid color-mix(in srgb, var(--accent-orange) 30%, transparent)',
        }
      : s === 'medium'
      ? {
          background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
          color: 'var(--accent-yellow)',
          border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
        }
      : {
          background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
          color: 'var(--accent-green)',
          border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
        }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase"
      style={style}
    >
      {severity}
    </span>
  )
}

function DaysCell({ days }: { days: number }) {
  const color =
    days <= 7
      ? 'var(--accent-red)'
      : days <= 30
      ? 'var(--accent-orange)'
      : 'var(--accent-yellow)'
  return (
    <span style={{ color, fontWeight: 600 }}>
      {days <= 0 ? `${Math.abs(days)}d ago` : `${days}d`}
    </span>
  )
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: number | string | null
  color?: string
}) {
  return (
    <div
      className="rounded-lg px-4 py-3 flex flex-col gap-0.5 min-w-[110px]"
      style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
    >
      <span
        className="text-[22px] font-bold"
        style={{ color: color ?? 'var(--text-primary)' }}
      >
        {value ?? '—'}
      </span>
      <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

function CertTypeBadge({ certType }: { certType: string }) {
  const isKv = certType.toLowerCase() === 'keyvault'
  const label = isKv ? 'Key Vault' : 'App Service'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium"
      style={{
        background: isKv
          ? 'color-mix(in srgb, var(--accent-blue) 12%, transparent)'
          : 'color-mix(in srgb, var(--accent-green) 12%, transparent)',
        color: isKv ? 'var(--accent-blue)' : 'var(--accent-green)',
        border: isKv
          ? '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)'
          : '1px solid color-mix(in srgb, var(--accent-green) 25%, transparent)',
      }}
    >
      {label}
    </span>
  )
}

export function CertExpiryTab() {
  const [findings, setFindings] = useState<CertFinding[]>([])
  const [summary, setSummary] = useState<CertSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const qs = new URLSearchParams()
      if (severityFilter) qs.set('severity', severityFilter)
      if (typeFilter) qs.set('cert_type', typeFilter)
      const qstr = qs.toString()

      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/certs/expiry${qstr ? `?${qstr}` : ''}`),
        fetch('/api/proxy/certs/summary'),
      ])

      if (findingsRes.ok) {
        const data = await findingsRes.json()
        setFindings(data.findings ?? [])
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
  }, [severityFilter, typeFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck
            className="h-5 w-5"
            aria-label="TLS certificate expiry"
            style={{ color: 'var(--accent-blue)' }}
          />
          <h2
            className="text-[15px] font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            TLS / Certificate Expiry
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="text-[12px] rounded px-2 py-1.5 outline-none"
            style={{
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="">All Types</option>
            <option value="keyvault">Key Vault</option>
            <option value="app_service">App Service</option>
          </select>
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
            <option value="low">Low</option>
          </select>
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="flex flex-wrap gap-3">
          <StatCard label="Total Expiring" value={summary.total} />
          <StatCard
            label="Critical (≤7d)"
            value={summary.critical_count}
            color="var(--accent-red)"
          />
          <StatCard
            label="High (≤30d)"
            value={summary.high_count}
            color="var(--accent-orange)"
          />
          <StatCard
            label="Medium (≤60d)"
            value={summary.medium_count}
            color="var(--accent-yellow)"
          />
          <StatCard
            label="Soonest Expiry"
            value={
              summary.soonest_expiry_days !== null
                ? `${summary.soonest_expiry_days}d`
                : null
            }
            color={
              summary.soonest_expiry_days !== null && summary.soonest_expiry_days <= 7
                ? 'var(--accent-red)'
                : summary.soonest_expiry_days !== null && summary.soonest_expiry_days <= 30
                ? 'var(--accent-orange)'
                : undefined
            }
          />
        </div>
      )}

      {/* Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        {loading ? (
          <div
            className="p-8 text-center text-[13px]"
            style={{ color: 'var(--text-secondary)' }}
          >
            Loading certificate findings…
          </div>
        ) : findings.length === 0 ? (
          <div
            className="p-8 text-center text-[13px]"
            style={{ color: 'var(--text-secondary)' }}
          >
            No expiring certificates found within 90 days.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Certificate Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Vault / App</TableHead>
                <TableHead>Expires On</TableHead>
                <TableHead>Days Remaining</TableHead>
                <TableHead>Severity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {findings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell className="font-medium text-[13px]">
                    {f.cert_name}
                  </TableCell>
                  <TableCell>
                    <CertTypeBadge certType={f.cert_type} />
                  </TableCell>
                  <TableCell
                    className="text-[13px]"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {f.vault_or_app_name || '—'}
                  </TableCell>
                  <TableCell
                    className="text-[13px]"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {f.expires_on ? new Date(f.expires_on).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell>
                    <DaysCell days={f.days_until_expiry} />
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={f.severity} />
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
