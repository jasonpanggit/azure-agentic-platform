'use client'

import { useState, useEffect, useCallback } from 'react'
import { ShieldAlert, CheckCircle, AlertTriangle, RefreshCw } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface CVERecord {
  readonly cve_id: string
  readonly description: string
  readonly severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  readonly cvss_score: number | null
  readonly affected_product: string
  readonly affected_versions: string
  readonly published_date: string | null
  readonly patched_kb_ids: readonly string[]
  readonly patched_by_installed: boolean
  readonly patched_by_pending: boolean
  readonly status: 'PATCHED' | 'PENDING_PATCH' | 'UNPATCHED'
}

type SeverityFilter = 'ALL' | 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
type StatusFilter = 'ALL' | 'UNPATCHED' | 'PENDING_PATCH' | 'PATCHED'

interface CVETabProps {
  vmName: string
  subscriptionId: string
  resourceGroup: string
  getAccessToken: () => Promise<string | null>
}

// ── Badge helpers ─────────────────────────────────────────────────────────────

function severityColor(severity: string): string {
  switch (severity) {
    case 'CRITICAL': return 'var(--accent-red)'
    case 'HIGH':     return 'var(--accent-orange)'
    case 'MEDIUM':   return 'var(--accent-yellow)'
    case 'LOW':      return 'var(--accent-blue)'
    default:         return 'var(--text-muted)'
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'PATCHED':      return 'var(--accent-green)'
    case 'PENDING_PATCH': return 'var(--accent-yellow)'
    case 'UNPATCHED':    return 'var(--accent-red)'
    default:             return 'var(--text-muted)'
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'PATCHED':      return 'Patched'
    case 'PENDING_PATCH': return 'Pending Patch'
    case 'UNPATCHED':    return 'Unpatched'
    default:             return status
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = severityColor(severity)
  return (
    <span
      className="inline-block text-[9px] font-bold px-1.5 py-0.5 rounded"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {severity}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const color = statusColor(status)
  return (
    <span
      className="inline-block text-[9px] font-bold px-1.5 py-0.5 rounded"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
      }}
    >
      {statusLabel(status)}
    </span>
  )
}

// ── CVETab ────────────────────────────────────────────────────────────────────

export function CVETab({ vmName, subscriptionId, resourceGroup, getAccessToken }: CVETabProps) {
  const [cves, setCves] = useState<readonly CVERecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('ALL')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')

  const fetchCves = useCallback(async () => {
    if (!vmName || !subscriptionId || !resourceGroup) return
    setLoading(true)
    setError(null)
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const params = new URLSearchParams({
        subscription_id: subscriptionId,
        resource_group: resourceGroup,
      })
      const res = await fetch(
        `/api/proxy/vms/${encodeURIComponent(vmName)}/cves?${params}`,
        { headers, signal: AbortSignal.timeout(15000) }
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setCves(data.cves ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load CVE data')
    } finally {
      setLoading(false)
    }
  }, [vmName, subscriptionId, resourceGroup, getAccessToken])

  useEffect(() => {
    fetchCves()
  }, [fetchCves])

  // ── Derived stats ─────────────────────────────────────────────────────────

  const stats = {
    total:    cves.length,
    critical: cves.filter(c => c.severity === 'CRITICAL').length,
    unpatched: cves.filter(c => c.status === 'UNPATCHED').length,
    patched:  cves.filter(c => c.status === 'PATCHED').length,
    pending:  cves.filter(c => c.status === 'PENDING_PATCH').length,
  }

  const filtered = cves.filter(c => {
    if (severityFilter !== 'ALL' && c.severity !== severityFilter) return false
    if (statusFilter !== 'ALL' && c.status !== statusFilter) return false
    return true
  })

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="p-4 space-y-3">

      {/* Summary stat chips */}
      <div className="grid grid-cols-5 gap-2">
        {[
          { label: 'Total CVEs',  value: loading ? '…' : String(stats.total),    color: 'var(--text-primary)' },
          { label: 'Critical',    value: loading ? '…' : String(stats.critical),  color: stats.critical > 0 ? 'var(--accent-red)' : 'var(--text-primary)' },
          { label: 'Unpatched',   value: loading ? '…' : String(stats.unpatched), color: stats.unpatched > 0 ? 'var(--accent-red)' : 'var(--text-primary)' },
          { label: 'Patched',     value: loading ? '…' : String(stats.patched),   color: stats.patched > 0 ? 'var(--accent-green)' : 'var(--text-primary)' },
          { label: 'Pending',     value: loading ? '…' : String(stats.pending),   color: stats.pending > 0 ? 'var(--accent-yellow)' : 'var(--text-primary)' },
        ].map(chip => (
          <div
            key={chip.label}
            className="flex flex-col items-center rounded-lg p-2"
            style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)' }}
          >
            <span className="font-mono text-sm font-semibold" style={{ color: chip.color }}>
              {chip.value}
            </span>
            <span className="text-[10px] text-center" style={{ color: 'var(--text-muted)' }}>{chip.label}</span>
          </div>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Severity filter */}
        <div className="flex items-center gap-1">
          {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as SeverityFilter[]).map(sv => (
            <button
              key={sv}
              onClick={() => setSeverityFilter(sv)}
              className="text-[10px] px-1.5 py-0.5 rounded cursor-pointer"
              style={{
                background: severityFilter === sv ? 'var(--accent-blue)' : 'var(--bg-subtle)',
                color: severityFilter === sv ? 'white' : 'var(--text-secondary)',
              }}
            >
              {sv === 'ALL' ? 'All Severity' : sv}
            </button>
          ))}
        </div>

        <div className="w-px h-4" style={{ background: 'var(--border)' }} />

        {/* Status filter */}
        <div className="flex items-center gap-1">
          {(['ALL', 'UNPATCHED', 'PENDING_PATCH', 'PATCHED'] as StatusFilter[]).map(st => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className="text-[10px] px-1.5 py-0.5 rounded cursor-pointer"
              style={{
                background: statusFilter === st ? 'var(--accent-blue)' : 'var(--bg-subtle)',
                color: statusFilter === st ? 'white' : 'var(--text-secondary)',
              }}
            >
              {st === 'ALL' ? 'All Status' : statusLabel(st)}
            </button>
          ))}
        </div>

        <button
          onClick={fetchCves}
          className="ml-auto p-1 rounded cursor-pointer"
          style={{ color: 'var(--text-muted)' }}
          title="Refresh CVEs"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 rounded animate-pulse" style={{ background: 'var(--bg-subtle)' }} />
          ))}
        </div>
      ) : error ? (
        <div className="py-8 text-center">
          <AlertTriangle className="h-6 w-6 mx-auto mb-2" style={{ color: 'var(--accent-red)' }} />
          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{error}</p>
          <button
            onClick={fetchCves}
            className="mt-2 text-xs px-3 py-1 rounded cursor-pointer"
            style={{ background: 'var(--bg-subtle)', color: 'var(--accent-blue)' }}
          >
            Retry
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-8 text-center">
          <CheckCircle className="h-6 w-6 mx-auto mb-2" style={{ color: 'var(--accent-green)' }} />
          <p className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
            {cves.length === 0 ? 'No CVEs found for this VM' : 'No CVEs match the current filters'}
          </p>
        </div>
      ) : (
        /* CVE table */
        <div className="rounded overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          {/* Header */}
          <div
            className="grid text-[10px] font-semibold uppercase tracking-wide px-3 py-2"
            style={{
              gridTemplateColumns: '1.5fr 0.6fr 0.5fr 2fr 1fr 1fr',
              background: 'var(--bg-canvas)',
              color: 'var(--text-muted)',
              borderBottom: '1px solid var(--border)',
            }}
          >
            <span>CVE ID</span>
            <span>Severity</span>
            <span>CVSS</span>
            <span>Description</span>
            <span>Status</span>
            <span>Patched By</span>
          </div>

          {/* Rows */}
          <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {filtered.map(cve => (
              <div
                key={cve.cve_id}
                className="grid items-center px-3 py-2 gap-2 text-xs"
                style={{
                  gridTemplateColumns: '1.5fr 0.6fr 0.5fr 2fr 1fr 1fr',
                  background: 'var(--bg-surface)',
                }}
              >
                {/* CVE ID — link to NVD */}
                <a
                  href={`https://nvd.nist.gov/vuln/detail/${cve.cve_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono font-medium hover:underline truncate"
                  style={{ color: 'var(--accent-blue)' }}
                  title={cve.cve_id}
                >
                  {cve.cve_id}
                </a>

                {/* Severity */}
                <SeverityBadge severity={cve.severity} />

                {/* CVSS */}
                <span style={{ color: 'var(--text-secondary)' }}>
                  {cve.cvss_score != null ? cve.cvss_score.toFixed(1) : '—'}
                </span>

                {/* Description */}
                <span
                  className="truncate"
                  style={{ color: 'var(--text-secondary)' }}
                  title={cve.description}
                >
                  {cve.description}
                </span>

                {/* Status */}
                <StatusBadge status={cve.status} />

                {/* Patched By */}
                <span className="font-mono text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>
                  {cve.patched_kb_ids.length > 0 ? cve.patched_kb_ids.join(', ') : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <p className="text-[10px] text-right" style={{ color: 'var(--text-muted)' }}>
          Showing {filtered.length} of {cves.length} CVEs
          {' · '}
          <span style={{ color: 'var(--accent-blue)' }}>
            Source: MSRC Security Update Guide
          </span>
        </p>
      )}
    </div>
  )
}
