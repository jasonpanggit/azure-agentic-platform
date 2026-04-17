'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FlaskConical, RefreshCw, X, Play, Beaker, AlertTriangle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Scenario {
  id: string
  name: string
  description: string
  domain: string
  severity: string
  expected_agent: string
}

interface ScenariosResponse {
  scenarios: Scenario[]
  total: number
  generated_at?: string
  error?: string
}

interface RunPayload {
  scenario_id: string
  subscription_id: string
  target_resource?: string
  resource_group?: string
  dry_run: boolean
}

interface RunResult {
  run_id: string
  scenario_id: string
  incident_id: string
  dry_run: boolean
  status: string
  triggered_at: string
  expected_agent: string
  error?: string
}

interface SimRun {
  run_id: string
  scenario_id: string
  scenario_name: string
  incident_id: string
  status: string
  triggered_by?: string
  dry_run: boolean
  subscription_id: string
  triggered_at?: string
}

interface RunsResponse {
  runs: SimRun[]
  total: number
  error?: string
}

// ---------------------------------------------------------------------------
// Domain color mapping — CSS semantic tokens only
// ---------------------------------------------------------------------------

const DOMAIN_COLORS: Record<string, string> = {
  compute: 'var(--accent-blue)',
  storage: 'var(--accent-purple)',
  network: 'var(--accent-cyan)',
  security: 'var(--accent-red)',
  arc: 'var(--accent-orange)',
  database: 'var(--accent-indigo)',
  finops: 'var(--accent-green)',
  messaging: 'var(--accent-yellow)',
}

function domainColor(domain: string): string {
  return DOMAIN_COLORS[domain.toLowerCase()] ?? 'var(--text-secondary)'
}

function DomainBadge({ domain }: { domain: string }) {
  const color = domainColor(domain)
  return (
    <Badge
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
        textTransform: 'capitalize',
      }}
    >
      {domain}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Severity badge
// ---------------------------------------------------------------------------

function severityColor(severity: string): string {
  switch (severity.toLowerCase()) {
    case 'sev0': return 'var(--accent-red)'
    case 'sev1': return 'var(--accent-orange)'
    case 'sev2': return 'var(--accent-yellow)'
    default: return 'var(--text-secondary)'
  }
}

function SeverityBadge({ severity }: { severity: string }) {
  const color = severityColor(severity)
  return (
    <Badge
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {severity.toUpperCase()}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Status badge for run history
// ---------------------------------------------------------------------------

function RunStatusBadge({ status }: { status: string }) {
  let color: string
  switch (status.toLowerCase()) {
    case 'triggered': color = 'var(--accent-blue)'; break
    case 'validated': color = 'var(--text-secondary)'; break
    case 'injection_failed': color = 'var(--accent-red)'; break
    default: color = 'var(--text-secondary)'
  }
  return (
    <Badge
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {status}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Run Modal
// ---------------------------------------------------------------------------

interface RunModalProps {
  scenario: Scenario
  subscriptionId: string
  initialDryRun: boolean
  onClose: () => void
  onSuccess: (result: RunResult) => void
}

function RunModal({ scenario, subscriptionId, initialDryRun, onClose, onSuccess }: RunModalProps) {
  const [targetResource, setTargetResource] = useState('')
  const [resourceGroup, setResourceGroup] = useState('')
  const [dryRun, setDryRun] = useState(initialDryRun)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<RunResult | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    const payload: RunPayload = {
      scenario_id: scenario.id,
      subscription_id: subscriptionId,
      dry_run: dryRun,
      ...(targetResource.trim() ? { target_resource: targetResource.trim() } : {}),
      ...(resourceGroup.trim() ? { resource_group: resourceGroup.trim() } : {}),
    }

    try {
      const res = await fetch('/api/proxy/simulations/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(15000),
      })
      const data: RunResult = await res.json()
      if (!res.ok) {
        setError((data as { error?: string }).error ?? `Request failed: ${res.status}`)
        return
      }
      setResult(data)
      onSuccess(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0"
        style={{ background: 'rgba(0,0,0,0.4)' }}
        onClick={onClose}
      />
      {/* Modal */}
      <div
        className="relative z-10 w-full max-w-lg rounded-xl p-6 shadow-xl"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-4 gap-3">
          <div>
            <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
              {result ? 'Simulation Triggered' : 'Trigger Simulation'}
            </h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              {scenario.name}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 transition-colors shrink-0"
            style={{ color: 'var(--text-secondary)' }}
            aria-label="Close modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scenario summary */}
        <div className="mb-4 p-3 rounded-lg space-y-2" style={{ background: 'var(--bg-subtle)' }}>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{scenario.description}</p>
          <div className="flex gap-2 flex-wrap">
            <DomainBadge domain={scenario.domain} />
            <SeverityBadge severity={scenario.severity} />
            <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              → <strong>{scenario.expected_agent}</strong>
            </span>
          </div>
        </div>

        {/* Result view */}
        {result ? (
          <div className="space-y-3">
            <div
              className="rounded-lg p-4 space-y-2"
              style={{
                background: 'color-mix(in srgb, var(--accent-green) 10%, transparent)',
                border: '1px solid color-mix(in srgb, var(--accent-green) 25%, transparent)',
              }}
            >
              <p className="text-sm font-medium" style={{ color: 'var(--accent-green)' }}>
                {result.dry_run ? '✓ Validation passed' : '✓ Simulation triggered'}
              </p>
              <div className="text-xs space-y-1" style={{ color: 'var(--text-secondary)' }}>
                <p>Run ID: <span className="font-mono" style={{ color: 'var(--text-primary)' }}>{result.run_id}</span></p>
                {result.incident_id && (
                  <p>Incident ID: <span className="font-mono" style={{ color: 'var(--text-primary)' }}>{result.incident_id}</span></p>
                )}
                <p>Status: <RunStatusBadge status={result.status} /></p>
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={onClose}>Close</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                Target Resource <span style={{ color: 'var(--text-muted)' }}>(optional)</span>
              </label>
              <Input
                placeholder="e.g. my-vm-001"
                value={targetResource}
                onChange={(e) => setTargetResource(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                Resource Group <span style={{ color: 'var(--text-muted)' }}>(optional)</span>
              </label>
              <Input
                placeholder="e.g. rg-prod"
                value={resourceGroup}
                onChange={(e) => setResourceGroup(e.target.value)}
              />
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm" style={{ color: 'var(--text-primary)' }}>
                Dry Run — validate only, don't inject incident
              </span>
            </label>

            {error && (
              <p className="text-xs" style={{ color: 'var(--accent-red)' }}>
                {error}
              </p>
            )}

            <div className="flex gap-2 justify-end">
              <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
                Cancel
              </Button>
              <Button type="submit" disabled={submitting} className="gap-1.5">
                <Play className="h-3.5 w-3.5" />
                {submitting ? 'Triggering…' : dryRun ? 'Validate' : 'Trigger Simulation'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Scenario card
// ---------------------------------------------------------------------------

interface ScenarioCardProps {
  scenario: Scenario
  onRun: (scenario: Scenario, dryRun: boolean) => void
}

function ScenarioCard({ scenario, onRun }: ScenarioCardProps) {
  return (
    <Card
      className="flex flex-col"
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
    >
      <CardContent className="p-4 flex flex-col gap-3 h-full">
        <div className="flex-1">
          <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>
            {scenario.name}
          </p>
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {scenario.description}
          </p>
        </div>

        <div className="flex flex-wrap gap-1.5 items-center">
          <DomainBadge domain={scenario.domain} />
          <SeverityBadge severity={scenario.severity} />
        </div>

        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          Agent: <strong style={{ color: 'var(--text-primary)' }}>{scenario.expected_agent}</strong>
        </p>

        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            className="flex-1 gap-1.5"
            onClick={() => onRun(scenario, false)}
          >
            <Play className="h-3.5 w-3.5" />
            Run
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() => onRun(scenario, true)}
          >
            <Beaker className="h-3.5 w-3.5" />
            Dry Run
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main SimulationTab component
// ---------------------------------------------------------------------------

interface SimulationTabProps {
  subscriptionId?: string
}

export function SimulationTab({ subscriptionId }: SimulationTabProps) {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [scenariosLoading, setScenariosLoading] = useState(false)
  const [scenariosError, setScenariosError] = useState<string | null>(null)

  const [runs, setRuns] = useState<SimRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsError, setRunsError] = useState<string | null>(null)

  const [modalState, setModalState] = useState<{ scenario: Scenario; dryRun: boolean } | null>(null)
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  const fetchScenarios = useCallback(async () => {
    setScenariosLoading(true)
    setScenariosError(null)
    try {
      const res = await fetch('/api/proxy/simulations', { signal: AbortSignal.timeout(15000) })
      const data: ScenariosResponse = await res.json()
      if (!res.ok) {
        setScenariosError(data.error ?? `Error: ${res.status}`)
        return
      }
      setScenarios(data.scenarios ?? [])
    } catch (err) {
      setScenariosError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setScenariosLoading(false)
    }
  }, [])

  const fetchRuns = useCallback(async () => {
    if (!subscriptionId) return
    setRunsLoading(true)
    setRunsError(null)
    const params = new URLSearchParams({ subscription_id: subscriptionId, limit: '50' })
    try {
      const res = await fetch(`/api/proxy/simulations/runs?${params}`, { signal: AbortSignal.timeout(15000) })
      const data: RunsResponse = await res.json()
      if (!res.ok) {
        setRunsError(data.error ?? `Error: ${res.status}`)
        return
      }
      setRuns(data.runs ?? [])
    } catch (err) {
      setRunsError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setRunsLoading(false)
    }
  }, [subscriptionId])

  useEffect(() => { fetchScenarios() }, [fetchScenarios])
  useEffect(() => { fetchRuns() }, [fetchRuns])

  function handleRunSuccess(result: RunResult) {
    const msg = result.dry_run
      ? `Dry run validated — run ID: ${result.run_id}`
      : `Simulation triggered — incident: ${result.incident_id}`
    setNotification({ type: 'success', message: msg })
    setTimeout(() => setNotification(null), 7000)
    // Refresh run history after a short delay to let backend record the run
    setTimeout(() => fetchRuns(), 1500)
  }

  function dismissNotification() { setNotification(null) }

  const bannerStyle = (type: 'success' | 'error'): React.CSSProperties => {
    const color = type === 'success' ? 'var(--accent-green)' : 'var(--accent-red)'
    return {
      background: `color-mix(in srgb, ${color} 15%, transparent)`,
      color,
      border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-5 w-5" style={{ color: 'var(--accent-blue)' }} />
          <div>
            <h1 className="text-lg font-semibold leading-tight" style={{ color: 'var(--text-primary)' }}>
              Incident Simulation
            </h1>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Validate platform health by triggering realistic incident scenarios
            </p>
          </div>
        </div>
      </div>

      {/* No subscription warning */}
      {!subscriptionId && (
        <div
          className="flex items-center gap-2 rounded-lg px-4 py-3 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
            color: 'var(--accent-yellow)',
            border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
          }}
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Select a subscription to run simulations
        </div>
      )}

      {/* Notification banner */}
      {notification && (
        <div
          className="flex items-center justify-between rounded-lg px-4 py-3 text-sm"
          style={bannerStyle(notification.type)}
        >
          <span>{notification.message}</span>
          <button onClick={dismissNotification} aria-label="Dismiss">
            <X className="h-3.5 w-3.5 ml-2" />
          </button>
        </div>
      )}

      {/* Scenarios section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Scenarios
          </h2>
          <Button variant="outline" size="sm" onClick={fetchScenarios} disabled={scenariosLoading} className="gap-1.5">
            <RefreshCw className={`h-3.5 w-3.5 ${scenariosLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>

        {scenariosError && (
          <div
            className="rounded-lg px-4 py-3 text-sm mb-3"
            style={bannerStyle('error')}
          >
            {scenariosError} &nbsp;
            <button className="underline" onClick={fetchScenarios}>Retry</button>
          </div>
        )}

        {scenariosLoading && scenarios.length === 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Card key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                <CardContent className="p-4 space-y-3">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-5/6" />
                  <div className="flex gap-2">
                    <Skeleton className="h-5 w-16" />
                    <Skeleton className="h-5 w-12" />
                  </div>
                  <div className="flex gap-2 pt-1">
                    <Skeleton className="h-8 flex-1" />
                    <Skeleton className="h-8 w-24" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : scenarios.length === 0 && !scenariosLoading ? (
          <div
            className="rounded-lg px-4 py-10 text-center text-sm"
            style={{ color: 'var(--text-secondary)', background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            No simulation scenarios available.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {scenarios.map((scenario) => (
              <ScenarioCard
                key={scenario.id}
                scenario={scenario}
                onRun={(s, dryRun) => {
                  if (!subscriptionId) return
                  setModalState({ scenario: s, dryRun })
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Run History section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Run History
          </h2>
          <Button variant="outline" size="sm" onClick={fetchRuns} disabled={runsLoading || !subscriptionId} className="gap-1.5">
            <RefreshCw className={`h-3.5 w-3.5 ${runsLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>

        {runsError && (
          <div
            className="rounded-lg px-4 py-3 text-sm mb-3"
            style={bannerStyle('error')}
          >
            {runsError} &nbsp;
            <button className="underline" onClick={fetchRuns}>Retry</button>
          </div>
        )}

        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border)' }}>
          <Table>
            <TableHeader>
              <TableRow style={{ background: 'var(--bg-subtle)' }}>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Scenario</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Incident ID</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Status</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Dry Run</TableHead>
                <TableHead style={{ color: 'var(--text-secondary)' }}>Triggered At</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runsLoading && runs.length === 0 ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 5 }).map((_, j) => (
                      <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                    ))}
                  </TableRow>
                ))
              ) : !subscriptionId ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-10 text-sm" style={{ color: 'var(--text-secondary)' }}>
                    Select a subscription to view run history.
                  </TableCell>
                </TableRow>
              ) : runs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-10 text-sm" style={{ color: 'var(--text-secondary)' }}>
                    No simulation runs yet. Trigger a scenario above to get started.
                  </TableCell>
                </TableRow>
              ) : (
                runs.map((run) => (
                  <TableRow key={run.run_id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <TableCell
                      className="text-sm font-medium max-w-[200px] truncate"
                      style={{ color: 'var(--text-primary)' }}
                      title={run.scenario_name}
                    >
                      {run.scenario_name}
                    </TableCell>
                    <TableCell
                      className="text-xs font-mono"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {run.incident_id || '—'}
                    </TableCell>
                    <TableCell>
                      <RunStatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                      {run.dry_run ? (
                        <span style={{ color: 'var(--accent-yellow)' }}>Yes</span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>No</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                      {run.triggered_at
                        ? new Date(run.triggered_at).toLocaleString()
                        : '—'}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Run Modal */}
      {modalState && subscriptionId && (
        <RunModal
          scenario={modalState.scenario}
          subscriptionId={subscriptionId}
          initialDryRun={modalState.dryRun}
          onClose={() => setModalState(null)}
          onSuccess={handleRunSuccess}
        />
      )}
    </div>
  )
}
