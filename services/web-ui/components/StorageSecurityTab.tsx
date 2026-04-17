'use client'

import { useEffect, useState, useCallback } from 'react'
import { HardDrive, RefreshCw, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface StorageFinding {
  id: string
  subscription_id: string
  resource_group: string
  account_name: string
  arm_id: string
  https_only: boolean
  allow_blob_public: boolean
  min_tls_version: string
  allow_shared_key: boolean
  network_default_action: string
  private_endpoint_count: number
  risk_score: number
  findings: string[]
  severity: string
  scanned_at: string
}

interface StorageSummary {
  total_accounts: number
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  top_risks: Array<{ description: string; count: number }>
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

function BoolCell({ value, positiveIsGood }: { value: boolean; positiveIsGood: boolean }) {
  const isGood = positiveIsGood ? value : !value
  return (
    <span
      style={{
        color: isGood ? 'var(--accent-green)' : 'var(--accent-red)',
        fontWeight: 600,
        fontSize: '12px',
      }}
    >
      {value ? 'Yes' : 'No'}
    </span>
  )
}

function RiskScoreBar({ score }: { score: number }) {
  const color =
    score >= 40
      ? 'var(--accent-red)'
      : score >= 25
      ? 'var(--accent-orange)'
      : score >= 10
      ? 'var(--accent-yellow)'
      : 'var(--accent-green)'
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 rounded-full overflow-hidden"
        style={{ width: 60, background: 'var(--border)' }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${score}%`, background: color }}
        />
      </div>
      <span className="text-[12px] font-semibold" style={{ color }}>
        {score}
      </span>
    </div>
  )
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
      <span
        className="text-[22px] font-bold"
        style={{ color: color ?? 'var(--text-primary)' }}
      >
        {value}
      </span>
      <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </span>
    </div>
  )
}

export function StorageSecurityTab() {
  const [findings, setFindings] = useState<StorageFinding[]>([])
  const [summary, setSummary] = useState<StorageSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const qs = severityFilter ? `?severity=${severityFilter}` : ''
      const [findingsRes, summaryRes] = await Promise.all([
        fetch(`/api/proxy/storage-security/findings${qs}`),
        fetch('/api/proxy/storage-security/summary'),
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
      // Network errors handled silently
    } finally {
      setLoading(false)
    }
  }, [severityFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  async function handleScan() {
    setScanning(true)
    try {
      await fetch('/api/proxy/storage-security/scan', { method: 'POST' })
      await fetchData()
    } catch {
      // Scan errors are non-fatal
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HardDrive
            className="h-5 w-5"
            aria-label="Storage account security"
            style={{ color: 'var(--accent-blue)' }}
          />
          <h2
            className="text-[15px] font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            Storage Account Security Audit
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
            <option value="low">Low</option>
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={handleScan}
            disabled={scanning}
            className="gap-1.5 text-[12px]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning…' : 'Scan Now'}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="flex flex-wrap gap-3">
          <StatCard label="Accounts Found" value={summary.total_accounts} />
          <StatCard
            label="Critical"
            value={summary.critical_count}
            color="var(--accent-red)"
          />
          <StatCard
            label="High"
            value={summary.high_count}
            color="var(--accent-orange)"
          />
          <StatCard
            label="Medium"
            value={summary.medium_count}
            color="var(--accent-yellow)"
          />
          <StatCard
            label="Low"
            value={summary.low_count}
            color="var(--accent-green)"
          />
        </div>
      )}

      {/* Top risks */}
      {summary && summary.top_risks.length > 0 && (
        <div
          className="rounded-lg px-4 py-3 space-y-1.5"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
        >
          <p className="text-[12px] font-semibold" style={{ color: 'var(--text-secondary)' }}>
            Top Risks
          </p>
          {summary.top_risks.map((r, i) => (
            <div key={i} className="flex items-center justify-between gap-4">
              <span className="text-[12px]" style={{ color: 'var(--text-primary)' }}>
                {r.description}
              </span>
              <span
                className="text-[11px] font-semibold shrink-0"
                style={{ color: 'var(--accent-orange)' }}
              >
                {r.count} account{r.count !== 1 ? 's' : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Findings table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        {loading ? (
          <div
            className="p-8 text-center text-[13px]"
            style={{ color: 'var(--text-secondary)' }}
          >
            Loading storage security findings…
          </div>
        ) : findings.length === 0 ? (
          <div
            className="p-8 text-center text-[13px]"
            style={{ color: 'var(--text-secondary)' }}
          >
            No storage security findings. Run a scan to check for misconfigurations.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account Name</TableHead>
                <TableHead>Resource Group</TableHead>
                <TableHead>HTTPS Only</TableHead>
                <TableHead>Blob Public</TableHead>
                <TableHead>Min TLS</TableHead>
                <TableHead>Network Policy</TableHead>
                <TableHead>Risk Score</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Findings</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {findings.map((f) => (
                <>
                  <TableRow
                    key={f.id}
                    style={{ cursor: f.findings.length > 0 ? 'pointer' : undefined }}
                    onClick={() =>
                      setExpandedId(expandedId === f.id ? null : f.id)
                    }
                  >
                    <TableCell className="font-medium text-[13px]">
                      {f.account_name}
                    </TableCell>
                    <TableCell
                      className="text-[13px]"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {f.resource_group}
                    </TableCell>
                    <TableCell>
                      <BoolCell value={f.https_only} positiveIsGood={true} />
                    </TableCell>
                    <TableCell>
                      <BoolCell value={f.allow_blob_public} positiveIsGood={false} />
                    </TableCell>
                    <TableCell
                      className="text-[12px] font-mono"
                      style={{
                        color:
                          f.min_tls_version.toUpperCase() === 'TLS1_0'
                            ? 'var(--accent-red)'
                            : 'var(--text-secondary)',
                      }}
                    >
                      {f.min_tls_version || '—'}
                    </TableCell>
                    <TableCell
                      className="text-[12px]"
                      style={{
                        color:
                          f.network_default_action.toLowerCase() === 'allow'
                            ? 'var(--accent-orange)'
                            : 'var(--accent-green)',
                        fontWeight: 600,
                      }}
                    >
                      {f.network_default_action || '—'}
                    </TableCell>
                    <TableCell>
                      <RiskScoreBar score={f.risk_score} />
                    </TableCell>
                    <TableCell>
                      <SeverityBadge severity={f.severity} />
                    </TableCell>
                    <TableCell>
                      {f.findings.length > 0 && (
                        <span
                          className="inline-flex items-center gap-1 text-[12px]"
                          style={{ color: 'var(--accent-orange)' }}
                        >
                          <AlertTriangle className="h-3 w-3" aria-label="findings" />
                          {f.findings.length}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                  {expandedId === f.id && f.findings.length > 0 && (
                    <TableRow key={`${f.id}-expanded`}>
                      <TableCell colSpan={9}>
                        <ul className="space-y-1 py-1">
                          {f.findings.map((desc, i) => (
                            <li
                              key={i}
                              className="text-[12px] flex items-start gap-2"
                              style={{ color: 'var(--text-secondary)' }}
                            >
                              <span
                                className="shrink-0 mt-0.5 h-1.5 w-1.5 rounded-full inline-block"
                                style={{ background: 'var(--accent-orange)' }}
                              />
                              {desc}
                            </li>
                          ))}
                        </ul>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
