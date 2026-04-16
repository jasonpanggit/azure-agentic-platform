'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { GitBranch, RefreshCw } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DriftSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

interface DriftFinding {
  finding_id: string
  resource_id: string
  resource_type: string
  resource_name: string
  attribute_path: string
  terraform_value: unknown
  live_value: unknown
  drift_severity: DriftSeverity
  detected_at: string
  description?: string
}

interface FindingsResponse {
  findings: DriftFinding[]
  total: number
  generated_at?: string
  error?: string
}

interface ScanResponse {
  job_id?: string
  status?: string
  error?: string
}

// ---------------------------------------------------------------------------
// SeverityBadge — CSS semantic tokens only, never hardcoded Tailwind colors
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: DriftSeverity }) {
  const styles: Record<DriftSeverity, React.CSSProperties> = {
    CRITICAL: {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
    },
    HIGH: {
      background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 20%, transparent)',
    },
    MEDIUM: {
      background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
      color: 'var(--accent-yellow)',
      border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
    },
    LOW: {
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
      border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
    },
  }
  return <Badge style={styles[severity]}>{severity}</Badge>
}

// ---------------------------------------------------------------------------
// SkeletonRows — loading placeholder
// ---------------------------------------------------------------------------

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 7 }).map((_, j) => (
            <TableCell key={j}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// DriftTab
// ---------------------------------------------------------------------------

const AUTO_REFRESH_MS = 5 * 60 * 1000 // 5 minutes

interface DriftTabProps {
  subscriptionId?: string
}

export function DriftTab({ subscriptionId }: DriftTabProps) {
  const [findings, setFindings] = useState<DriftFinding[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scanMessage, setScanMessage] = useState<string | null>(null)
  const [fixDiffs, setFixDiffs] = useState<Record<string, string>>({})
  const [loadingFix, setLoadingFix] = useState<Record<string, boolean>>({})
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchFindings = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ limit: '50' })
      const res = await fetch(`/api/proxy/drift/findings?${params.toString()}`)
      const data: FindingsResponse = await res.json()
      if (!res.ok || data.error) {
        setError(data.error ?? `Error ${res.status}`)
        setFindings([])
        setTotal(0)
      } else {
        setFindings(data.findings ?? [])
        setTotal(data.total ?? 0)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch findings')
      setFindings([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial load + auto-refresh
  useEffect(() => {
    void fetchFindings()
    refreshTimerRef.current = setInterval(() => void fetchFindings(), AUTO_REFRESH_MS)
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current)
    }
  }, [fetchFindings])

  async function handleTriggerScan() {
    setScanning(true)
    setScanMessage(null)
    try {
      const res = await fetch('/api/proxy/drift/scan', { method: 'POST' })
      const data: ScanResponse = await res.json()
      if (!res.ok || data.error) {
        setScanMessage(`Scan failed: ${data.error ?? res.status}`)
      } else {
        setScanMessage(`Scan queued (job: ${data.job_id ?? 'unknown'}). Refreshing in 10s…`)
        setTimeout(() => void fetchFindings(), 10000)
      }
    } catch (err) {
      setScanMessage(err instanceof Error ? err.message : 'Failed to trigger scan')
    } finally {
      setScanning(false)
    }
  }

  async function handleProposeFix(findingId: string) {
    setLoadingFix((prev) => ({ ...prev, [findingId]: true }))
    try {
      const res = await fetch(`/api/proxy/drift/findings/${findingId}/fix`)
      if (!res.ok) {
        setFixDiffs((prev) => ({ ...prev, [findingId]: `Error ${res.status}` }))
        return
      }
      const data = await res.json()
      setFixDiffs((prev) => ({ ...prev, [findingId]: data.diff ?? '# No diff available' }))
    } catch (err) {
      setFixDiffs((prev) => ({
        ...prev,
        [findingId]: err instanceof Error ? err.message : 'Error fetching fix',
      }))
    } finally {
      setLoadingFix((prev) => ({ ...prev, [findingId]: false }))
    }
  }

  function formatValue(val: unknown): string {
    if (val === null || val === undefined) return '—'
    if (typeof val === 'object') return JSON.stringify(val)
    return String(val)
  }

  function formatDetected(iso: string): string {
    try {
      return new Date(iso).toLocaleString()
    } catch {
      return iso
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 rounded-lg"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <GitBranch className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <span className="font-semibold text-sm" style={{ color: 'var(--text-primary)' }}>
            IaC Drift Detection
          </span>
          {total > 0 && (
            <Badge
              style={{
                background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                color: 'var(--accent-red)',
                border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
              }}
            >
              {total} finding{total !== 1 ? 's' : ''}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchFindings()}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={() => void handleTriggerScan()}
            disabled={scanning}
            style={{ background: 'var(--accent-blue)', color: '#fff' }}
          >
            {scanning ? 'Scanning…' : 'Trigger Scan'}
          </Button>
        </div>
      </div>

      {/* Scan message */}
      {scanMessage && (
        <div
          className="px-4 py-2 rounded text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
            color: 'var(--accent-blue)',
            border: '1px solid color-mix(in srgb, var(--accent-blue) 20%, transparent)',
          }}
        >
          {scanMessage}
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="px-4 py-2 rounded text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            color: 'var(--accent-red)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 20%, transparent)',
          }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        <Table>
          <TableHeader>
            <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
              {['Resource', 'Type', 'Attribute', 'Terraform Value', 'Live Value', 'Severity', 'Detected'].map(
                (h) => (
                  <TableHead
                    key={h}
                    className="text-xs font-semibold"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    {h}
                  </TableHead>
                )
              )}
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <SkeletonRows />
            ) : findings.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="py-12 text-center text-sm"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  <div className="flex flex-col items-center gap-2">
                    <GitBranch className="h-8 w-8 opacity-30" />
                    <span>No drift detected — infrastructure matches Terraform state</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              findings.map((f) => (
                <React.Fragment key={f.finding_id}>
                  <TableRow
                    className="text-sm"
                    style={{ borderBottom: '1px solid var(--border)' }}
                  >
                    <TableCell
                      className="max-w-[180px] truncate font-mono text-xs"
                      style={{ color: 'var(--text-primary)' }}
                      title={f.resource_id}
                    >
                      {f.resource_name || f.resource_id.split('/').pop()}
                    </TableCell>
                    <TableCell
                      className="font-mono text-xs"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {f.resource_type}
                    </TableCell>
                    <TableCell
                      className="font-mono text-xs"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {f.attribute_path}
                    </TableCell>
                    <TableCell
                      className="max-w-[120px] truncate font-mono text-xs"
                      style={{ color: 'var(--accent-green)' }}
                      title={formatValue(f.terraform_value)}
                    >
                      {formatValue(f.terraform_value)}
                    </TableCell>
                    <TableCell
                      className="max-w-[120px] truncate font-mono text-xs"
                      style={{ color: 'var(--accent-yellow)' }}
                      title={formatValue(f.live_value)}
                    >
                      {formatValue(f.live_value)}
                    </TableCell>
                    <TableCell>
                      <SeverityBadge severity={f.drift_severity} />
                    </TableCell>
                    <TableCell
                      className="text-xs"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {formatDetected(f.detected_at)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void handleProposeFix(f.finding_id)}
                        disabled={loadingFix[f.finding_id]}
                      >
                        {loadingFix[f.finding_id] ? '…' : 'Propose Fix'}
                      </Button>
                    </TableCell>
                  </TableRow>
                  {/* Inline diff display */}
                  {fixDiffs[f.finding_id] && (
                    <TableRow>
                      <TableCell colSpan={8} className="p-0">
                        <pre
                          className="text-xs p-3 overflow-x-auto"
                          style={{
                            background: 'var(--bg-subtle)',
                            color: 'var(--text-primary)',
                            borderTop: '1px solid var(--border)',
                            fontFamily: 'monospace',
                          }}
                        >
                          {fixDiffs[f.finding_id]}
                        </pre>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
