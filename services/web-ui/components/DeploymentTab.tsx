'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { DeploymentBadge } from './DeploymentBadge'
import { ExternalLink, GitCommit, GitPullRequest, RefreshCw } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DeploymentStatus = 'success' | 'failure' | 'in_progress' | 'queued' | 'cancelled'

interface Deployment {
  deployment_id: string
  source: string
  repository: string
  environment: string
  status: DeploymentStatus
  commit_sha: string
  author: string
  pipeline_url?: string
  resource_group?: string
  started_at: string
  completed_at?: string | null
  time_before_incident_min?: number | null
}

interface DeploymentListResponse {
  deployments: Deployment[]
  total: number
  hours_back: number
  error?: string
}

type StatusFilter = 'all' | 'success' | 'failure' | 'in_progress'

// ---------------------------------------------------------------------------
// StatusBadge — CSS semantic tokens only
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: DeploymentStatus }) {
  const styles: Record<DeploymentStatus, React.CSSProperties> = {
    success: {
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
      border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
    },
    failure: {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
    },
    in_progress: {
      background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
      color: 'var(--accent-yellow)',
      border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
    },
    queued: {
      background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
      color: 'var(--accent-blue)',
      border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
    },
    cancelled: {
      background: 'color-mix(in srgb, var(--text-secondary) 12%, transparent)',
      color: 'var(--text-secondary)',
      border: '1px solid color-mix(in srgb, var(--text-secondary) 20%, transparent)',
    },
  }

  const labels: Record<DeploymentStatus, string> = {
    success: 'Success',
    failure: 'Failed',
    in_progress: 'In Progress',
    queued: 'Queued',
    cancelled: 'Cancelled',
  }

  const style = styles[status] ?? styles.cancelled

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={style}
    >
      {labels[status] ?? status}
    </span>
  )
}

// ---------------------------------------------------------------------------
// CorrelatedIncidentsPanel — shows correlated incidents for a selected deployment
// ---------------------------------------------------------------------------

interface CorrelatedPanel {
  deployment: Deployment
  correlated: Deployment[]
  loading: boolean
  error?: string
}

function CorrelatedIncidentsPanel({ panel }: { panel: CorrelatedPanel }) {
  const { deployment, correlated, loading, error } = panel

  return (
    <Card style={{ border: '1px solid var(--border)', background: 'var(--bg-subtle)' }}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <GitPullRequest className="h-4 w-4" style={{ color: 'var(--accent-blue)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Correlated incidents for{' '}
            <code className="font-mono text-xs">{deployment.commit_sha.slice(0, 7)}</code>
            {' '}in <strong>{deployment.repository}</strong>
          </span>
        </div>

        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-3/4" />
          </div>
        )}

        {error && (
          <p className="text-xs" style={{ color: 'var(--accent-red)' }}>
            {error}
          </p>
        )}

        {!loading && !error && correlated.length === 0 && (
          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            No correlated incidents found in the ±30min window around this deployment.
          </p>
        )}

        {!loading && correlated.length > 0 && (
          <div className="space-y-2">
            {correlated.map((dep) => (
              <div
                key={dep.deployment_id}
                className="flex items-center gap-2 text-xs"
                style={{ color: 'var(--text-primary)' }}
              >
                <DeploymentBadge
                  deployment={{
                    author: dep.author,
                    commit_sha: dep.commit_sha,
                    pipeline_url: dep.pipeline_url,
                    time_before_incident_min: dep.time_before_incident_min ?? null,
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// DeploymentTab
// ---------------------------------------------------------------------------

interface DeploymentTabProps {
  resourceGroup?: string
}

export function DeploymentTab({ resourceGroup }: DeploymentTabProps) {
  const [deployments, setDeployments] = useState<Deployment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [hoursBack, setHoursBack] = useState(24)
  const [selectedDeployment, setSelectedDeployment] = useState<Deployment | null>(null)
  const [correlatedPanel, setCorrelatedPanel] = useState<CorrelatedPanel | null>(null)

  const fetchDeployments = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ hours_back: String(hoursBack), limit: '50' })
      if (resourceGroup) params.set('resource_group', resourceGroup)

      const res = await fetch(`/api/proxy/deployments?${params.toString()}`)
      const data: DeploymentListResponse = await res.json()

      if (!res.ok) {
        setError(data.error ?? `Request failed: ${res.status}`)
        setDeployments([])
      } else {
        setDeployments(data.deployments ?? [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load deployments')
      setDeployments([])
    } finally {
      setLoading(false)
    }
  }, [resourceGroup, hoursBack])

  useEffect(() => {
    void fetchDeployments()
  }, [fetchDeployments])

  const fetchCorrelated = useCallback(async (deployment: Deployment) => {
    setSelectedDeployment(deployment)
    setCorrelatedPanel({ deployment, correlated: [], loading: true })

    try {
      const params = new URLSearchParams({
        incident_timestamp: deployment.started_at,
      })
      if (deployment.resource_group) params.set('resource_group', deployment.resource_group)

      const res = await fetch(`/api/proxy/deployments/correlate?${params.toString()}`)
      const data = await res.json()

      if (!res.ok) {
        setCorrelatedPanel((prev) =>
          prev ? { ...prev, loading: false, error: data.error ?? 'Correlation failed' } : prev
        )
      } else {
        setCorrelatedPanel({
          deployment,
          correlated: data.correlated_deployments ?? [],
          loading: false,
        })
      }
    } catch (err) {
      setCorrelatedPanel((prev) =>
        prev
          ? {
              ...prev,
              loading: false,
              error: err instanceof Error ? err.message : 'Correlation error',
            }
          : prev
      )
    }
  }, [])

  const filteredDeployments = deployments.filter((d) => {
    if (statusFilter === 'all') return true
    return d.status === statusFilter
  })

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return iso
    }
  }

  const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'success', label: 'Success' },
    { value: 'failure', label: 'Failed' },
    { value: 'in_progress', label: 'In Progress' },
  ]

  const TIME_RANGES = [
    { value: 6, label: '6h' },
    { value: 24, label: '24h' },
    { value: 48, label: '48h' },
    { value: 168, label: '7d' },
  ]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <GitPullRequest
            className="h-5 w-5"
            style={{ color: 'var(--accent-blue)' }}
            aria-hidden="true"
          />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
            Deployments
          </h2>
          {!loading && (
            <span
              className="text-xs px-1.5 py-0.5 rounded-full"
              style={{
                background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                color: 'var(--accent-blue)',
              }}
            >
              {filteredDeployments.length}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Status filter */}
          <div className="flex items-center gap-1">
            {STATUS_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setStatusFilter(value)}
                className="px-2.5 py-1 rounded text-xs font-medium transition-colors cursor-pointer"
                style={{
                  background:
                    statusFilter === value
                      ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
                      : 'var(--bg-subtle)',
                  color:
                    statusFilter === value ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  border:
                    statusFilter === value
                      ? '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)'
                      : '1px solid var(--border)',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Time range filter */}
          <div className="flex items-center gap-1">
            {TIME_RANGES.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setHoursBack(value)}
                className="px-2.5 py-1 rounded text-xs font-medium transition-colors cursor-pointer"
                style={{
                  background:
                    hoursBack === value
                      ? 'color-mix(in srgb, var(--accent-blue) 15%, transparent)'
                      : 'var(--bg-subtle)',
                  color: hoursBack === value ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  border:
                    hoursBack === value
                      ? '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)'
                      : '1px solid var(--border)',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchDeployments()}
            disabled={loading}
            className="h-7 text-xs gap-1.5"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}
      >
        <Table>
          <TableHeader>
            <TableRow style={{ borderBottom: '1px solid var(--border)' }}>
              {['Time', 'Repository', 'Environment', 'Status', 'Author', 'Commit', 'Correlated Incidents'].map(
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
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}

            {!loading && filteredDeployments.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-12 text-center">
                  <div className="flex flex-col items-center gap-3">
                    <GitCommit
                      className="h-8 w-8 opacity-30"
                      style={{ color: 'var(--text-secondary)' }}
                    />
                    <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                      No deployments recorded
                    </p>
                    <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      Set up the GitHub webhook:{' '}
                      <code
                        className="font-mono px-1.5 py-0.5 rounded"
                        style={{ background: 'var(--bg-subtle)' }}
                      >
                        POST /api/v1/deployments
                      </code>
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            )}

            {!loading &&
              filteredDeployments.map((dep) => {
                const isSelected = selectedDeployment?.deployment_id === dep.deployment_id
                return (
                  <TableRow
                    key={dep.deployment_id}
                    onClick={() => void fetchCorrelated(dep)}
                    className="cursor-pointer transition-colors"
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: isSelected
                        ? 'color-mix(in srgb, var(--accent-blue) 8%, transparent)'
                        : undefined,
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected)
                        e.currentTarget.style.background = 'var(--bg-subtle)'
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) e.currentTarget.style.background = ''
                    }}
                  >
                    <TableCell
                      className="text-xs font-mono whitespace-nowrap"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {formatTime(dep.started_at)}
                    </TableCell>
                    <TableCell
                      className="text-xs font-medium"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {dep.repository}
                    </TableCell>
                    <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {dep.environment}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={dep.status} />
                    </TableCell>
                    <TableCell
                      className="text-xs"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      @{dep.author}
                    </TableCell>
                    <TableCell>
                      {dep.pipeline_url ? (
                        <a
                          href={dep.pipeline_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs font-mono hover:underline"
                          style={{ color: 'var(--accent-blue)' }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {dep.commit_sha.slice(0, 7)}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span
                          className="text-xs font-mono"
                          style={{ color: 'var(--text-secondary)' }}
                        >
                          {dep.commit_sha.slice(0, 7)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {isSelected && correlatedPanel ? (
                        correlatedPanel.loading ? (
                          <Skeleton className="h-4 w-16" />
                        ) : correlatedPanel.correlated.length > 0 ? (
                          <span
                            className="px-1.5 py-0.5 rounded text-xs"
                            style={{
                              background:
                                'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
                              color: 'var(--accent-yellow)',
                            }}
                          >
                            {correlatedPanel.correlated.length} found
                          </span>
                        ) : (
                          'None'
                        )
                      ) : (
                        '—'
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
          </TableBody>
        </Table>
      </div>

      {/* Correlated incidents panel */}
      {correlatedPanel && (
        <CorrelatedIncidentsPanel panel={correlatedPanel} />
      )}
    </div>
  )
}
