'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  ChevronDown,
  ChevronUp,
  Play,
  Plus,
  Save,
  Trash2,
  Info,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OnFailure = 'abort' | 'continue' | 'rollback'

interface AutomationStep {
  step_id: string
  tool_name: string
  parameters_template: Record<string, unknown>
  condition: string | null
  require_approval: boolean
  on_failure: OnFailure
}

interface AvailableTool {
  tool_name: string
  description: string
  domain: string
}

type StepStatus = 'idle' | 'pending' | 'awaiting_approval' | 'success' | 'failed' | 'rollback_step'

interface StepExecutionState {
  status: StepStatus
  result?: Record<string, unknown>
  approval_id?: string
  duration_ms?: number
}

interface RunbookAutomationStudioProps {
  runbookId: string
  runbookName?: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateStepId(): string {
  return `step_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
}

function defaultStep(toolName = ''): AutomationStep {
  return {
    step_id: generateStepId(),
    tool_name: toolName,
    parameters_template: {},
    condition: null,
    require_approval: true,
    on_failure: 'abort',
  }
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '{}'
  }
}

function parseJsonSafe(text: string): { value: Record<string, unknown> | null; error: string | null } {
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
      return { value: null, error: 'Must be a JSON object' }
    }
    return { value: parsed as Record<string, unknown>, error: null }
  } catch {
    return { value: null, error: 'Invalid JSON' }
  }
}

// ---------------------------------------------------------------------------
// StepStatusBadge
// ---------------------------------------------------------------------------

function StepStatusBadge({ status }: { status: StepStatus }) {
  const styles: Record<StepStatus, React.CSSProperties> = {
    idle: {
      background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
      color: 'var(--text-secondary)',
      border: '1px solid color-mix(in srgb, var(--border) 60%, transparent)',
    },
    pending: {
      background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
      color: 'var(--accent-yellow)',
      border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
    },
    awaiting_approval: {
      background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
      color: 'var(--accent-blue)',
      border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
    },
    success: {
      background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
      color: 'var(--accent-green)',
      border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
    },
    failed: {
      background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
      color: 'var(--accent-red)',
      border: '1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)',
    },
    rollback_step: {
      background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
      color: 'var(--accent-yellow)',
      border: '1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
    },
  }
  const labels: Record<StepStatus, string> = {
    idle: 'Idle',
    pending: 'Running',
    awaiting_approval: 'Awaiting Approval',
    success: 'Success',
    failed: 'Failed',
    rollback_step: 'Rolled Back',
  }
  return <Badge style={styles[status]}>{labels[status]}</Badge>
}

// ---------------------------------------------------------------------------
// StepCard
// ---------------------------------------------------------------------------

interface StepCardProps {
  step: AutomationStep
  index: number
  total: number
  tools: AvailableTool[]
  executionState: StepExecutionState | undefined
  onChange: (updated: AutomationStep) => void
  onRemove: () => void
  onMoveUp: () => void
  onMoveDown: () => void
}

function StepCard({
  step,
  index,
  total,
  tools,
  executionState,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: StepCardProps) {
  const [paramsText, setParamsText] = useState(() => formatJson(step.parameters_template))
  const [paramsError, setParamsError] = useState<string | null>(null)

  const handleParamsChange = useCallback(
    (text: string) => {
      setParamsText(text)
      const { value, error } = parseJsonSafe(text)
      if (error) {
        setParamsError(error)
      } else {
        setParamsError(null)
        onChange({ ...step, parameters_template: value ?? {} })
      }
    },
    [step, onChange]
  )

  const status = executionState?.status ?? 'idle'

  return (
    <Card
      style={{
        border: '1px solid var(--border)',
        background: 'var(--bg-surface)',
        marginBottom: '0.75rem',
      }}
    >
      <CardContent style={{ padding: '1rem' }}>
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '1.5rem',
              height: '1.5rem',
              borderRadius: '9999px',
              background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
              color: 'var(--accent-blue)',
              fontSize: '0.75rem',
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            {index + 1}
          </span>
          <span style={{ fontWeight: 500, color: 'var(--text-primary)', flex: 1 }}>
            {step.tool_name || 'New Step'}
          </span>
          <StepStatusBadge status={status} />
          <div style={{ display: 'flex', gap: '0.25rem' }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={onMoveUp}
              disabled={index === 0}
              aria-label="Move step up"
              style={{ color: 'var(--text-secondary)', padding: '0.25rem' }}
            >
              <ChevronUp size={14} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onMoveDown}
              disabled={index === total - 1}
              aria-label="Move step down"
              style={{ color: 'var(--text-secondary)', padding: '0.25rem' }}
            >
              <ChevronDown size={14} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onRemove}
              aria-label="Remove step"
              style={{ color: 'var(--accent-red)', padding: '0.25rem' }}
            >
              <Trash2 size={14} />
            </Button>
          </div>
        </div>

        {/* Tool selector */}
        <div style={{ marginBottom: '0.75rem' }}>
          <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>
            Tool
          </label>
          <Select
            value={step.tool_name}
            onValueChange={(value) => onChange({ ...step, tool_name: value })}
          >
            <SelectTrigger style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
              <SelectValue placeholder="Select a tool…" />
            </SelectTrigger>
            <SelectContent>
              {tools.map((t) => (
                <SelectItem key={t.tool_name} value={t.tool_name}>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{t.tool_name}</span>
                  <span style={{ marginLeft: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                    — {t.description}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Parameters template */}
        <div style={{ marginBottom: '0.75rem' }}>
          <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.25rem' }}>
            Parameters Template (JSON with Jinja2 variables)
          </label>
          <textarea
            value={paramsText}
            onChange={(e) => handleParamsChange(e.target.value)}
            rows={4}
            spellCheck={false}
            style={{
              width: '100%',
              fontFamily: 'monospace',
              fontSize: '0.8rem',
              padding: '0.5rem',
              background: 'var(--bg-canvas)',
              border: `1px solid ${paramsError ? 'var(--accent-red)' : 'var(--border)'}`,
              borderRadius: '0.375rem',
              color: 'var(--text-primary)',
              resize: 'vertical',
              outline: 'none',
            }}
          />
          {paramsError && (
            <p style={{ color: 'var(--accent-red)', fontSize: '0.7rem', marginTop: '0.2rem' }}>
              {paramsError}
            </p>
          )}
        </div>

        {/* Controls row */}
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Require approval toggle */}
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer', fontSize: '0.8rem', color: 'var(--text-primary)' }}>
            <input
              type="checkbox"
              checked={step.require_approval}
              onChange={(e) => onChange({ ...step, require_approval: e.target.checked })}
              style={{ accentColor: 'var(--accent-blue)' }}
            />
            Require HITL approval
          </label>

          {/* On failure select */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>On failure:</span>
            <Select
              value={step.on_failure}
              onValueChange={(value) => onChange({ ...step, on_failure: value as OnFailure })}
            >
              <SelectTrigger
                style={{
                  background: 'var(--bg-canvas)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  width: '8rem',
                  fontSize: '0.8rem',
                }}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="abort">Abort</SelectItem>
                <SelectItem value="continue">Continue</SelectItem>
                <SelectItem value="rollback">Rollback</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Execution result overlay */}
        {executionState && executionState.status !== 'idle' && (
          <div
            style={{
              marginTop: '0.75rem',
              padding: '0.5rem',
              borderRadius: '0.375rem',
              background: 'var(--bg-canvas)',
              border: '1px solid var(--border)',
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
            }}
          >
            {executionState.approval_id && (
              <p>
                Approval ID:{' '}
                <code style={{ fontFamily: 'monospace', color: 'var(--accent-blue)' }}>
                  {executionState.approval_id}
                </code>
              </p>
            )}
            {executionState.duration_ms !== undefined && (
              <p>Duration: {executionState.duration_ms}ms</p>
            )}
            {executionState.result && (
              <pre style={{ marginTop: '0.25rem', overflow: 'auto', maxHeight: '6rem' }}>
                {formatJson(executionState.result)}
              </pre>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// RunbookAutomationStudio
// ---------------------------------------------------------------------------

export default function RunbookAutomationStudio({
  runbookId,
  runbookName,
}: RunbookAutomationStudioProps) {
  const [steps, setSteps] = useState<AutomationStep[]>([])
  const [tools, setTools] = useState<AvailableTool[]>([])
  const [toolsLoading, setToolsLoading] = useState(true)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'complete' | 'error'>('idle')
  const [runMessage, setRunMessage] = useState<string | null>(null)
  const [executionMap, setExecutionMap] = useState<Record<string, StepExecutionState>>({})
  const abortRef = useRef<AbortController | null>(null)

  // Load available tools
  useEffect(() => {
    setToolsLoading(true)
    fetch('/api/proxy/runbooks/tools')
      .then((r) => r.json())
      .then((data) => {
        setTools(Array.isArray(data.tools) ? data.tools : [])
      })
      .catch(() => {
        setTools([])
      })
      .finally(() => setToolsLoading(false))
  }, [])

  // ---------------------------------------------------------------------------
  // Step mutation helpers
  // ---------------------------------------------------------------------------

  const addStep = useCallback(() => {
    setSteps((prev) => [...prev, defaultStep()])
  }, [])

  const removeStep = useCallback((idx: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== idx))
  }, [])

  const updateStep = useCallback((idx: number, updated: AutomationStep) => {
    setSteps((prev) => prev.map((s, i) => (i === idx ? updated : s)))
  }, [])

  const moveStep = useCallback((idx: number, direction: -1 | 1) => {
    setSteps((prev) => {
      const next = [...prev]
      const target = idx + direction
      if (target < 0 || target >= next.length) return prev
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return next
    })
  }, [])

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------

  const handleSave = useCallback(async () => {
    setSaveStatus('saving')
    try {
      const res = await fetch(`/api/proxy/runbooks/${encodeURIComponent(runbookId)}/automation-steps`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ automation_steps: steps }),
      })
      if (!res.ok) {
        setSaveStatus('error')
        return
      }
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }, [runbookId, steps])

  // ---------------------------------------------------------------------------
  // Execute / Dry Run
  // ---------------------------------------------------------------------------

  const handleRun = useCallback(
    async (dryRun: boolean) => {
      if (abortRef.current) abortRef.current.abort()
      abortRef.current = new AbortController()

      setRunStatus('running')
      setRunMessage(null)
      setExecutionMap({})

      const incidentContext = {
        resource_id: '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-test',
        subscription_id: '00000000-0000-0000-0000-000000000000',
      }

      try {
        const url = `/api/proxy/runbooks/${encodeURIComponent(runbookId)}/execute?dry_run=${dryRun}`
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ incident_context: incidentContext }),
          signal: abortRef.current.signal,
        })

        if (!res.ok || !res.body) {
          setRunStatus('error')
          setRunMessage(`Request failed: ${res.status}`)
          return
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6)) as Record<string, unknown>
              const type = event.type as string

              if (type === 'step') {
                const stepId = event.step_id as string
                const status = event.status as StepStatus
                setExecutionMap((prev) => ({
                  ...prev,
                  [stepId]: {
                    status,
                    result: event.result as Record<string, unknown> | undefined,
                    approval_id: event.approval_id as string | undefined,
                    duration_ms: event.duration_ms as number | undefined,
                  },
                }))
              } else if (type === 'runbook_complete') {
                setRunStatus('complete')
                setRunMessage(dryRun ? 'Dry run complete.' : 'Runbook executed successfully.')
              } else if (type === 'runbook_aborted') {
                setRunStatus('error')
                setRunMessage(`Aborted: ${event.reason ?? 'unknown reason'}`)
              } else if (type === 'error') {
                setRunStatus('error')
                setRunMessage(`Error: ${event.message ?? 'unknown error'}`)
              } else if (type === 'rollback_step') {
                const stepId = event.step_id as string
                setExecutionMap((prev) => ({
                  ...prev,
                  [stepId]: { ...prev[stepId], status: 'rollback_step' },
                }))
              }
            } catch {
              // skip malformed SSE line
            }
          }
        }

        if (runStatus === 'running') setRunStatus('complete')
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setRunStatus('error')
          setRunMessage((err as Error).message ?? 'Stream error')
        }
      }
    },
    [runbookId, runStatus]
  )

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={{ padding: '1rem', color: 'var(--text-primary)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            Runbook Automation Studio
          </h2>
          {runbookName && (
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
              {runbookName} · <code style={{ fontFamily: 'monospace' }}>{runbookId}</code>
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleRun(true)}
            disabled={runStatus === 'running' || steps.length === 0}
            style={{ borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <Play size={14} style={{ marginRight: '0.35rem' }} />
            Dry Run
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saveStatus === 'saving'}
            style={{
              background: 'var(--accent-blue)',
              color: '#fff',
              border: 'none',
            }}
          >
            <Save size={14} style={{ marginRight: '0.35rem' }} />
            {saveStatus === 'saving' ? 'Saving…' : saveStatus === 'saved' ? 'Saved!' : 'Save Steps'}
          </Button>
        </div>
      </div>

      {/* Jinja2 template helper */}
      <Alert style={{ marginBottom: '1rem', background: 'color-mix(in srgb, var(--accent-blue) 8%, transparent)', border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)' }}>
        <Info size={14} style={{ color: 'var(--accent-blue)', marginRight: '0.5rem', flexShrink: 0 }} />
        <AlertDescription style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--text-primary)' }}>Available template variables:</strong>{' '}
          <code style={{ fontFamily: 'monospace' }}>{'{{ incident.resource_id }}'}</code>,{' '}
          <code style={{ fontFamily: 'monospace' }}>{'{{ incident.subscription_id }}'}</code>,{' '}
          <code style={{ fontFamily: 'monospace' }}>{'{{ incident.node_name | default("unknown") }}'}</code>,{' '}
          <code style={{ fontFamily: 'monospace' }}>{'{{ incident.queue_name | default("") }}'}</code>
        </AlertDescription>
      </Alert>

      {/* Run status banner */}
      {runMessage && (
        <Alert
          style={{
            marginBottom: '1rem',
            background: runStatus === 'error'
              ? 'color-mix(in srgb, var(--accent-red) 10%, transparent)'
              : 'color-mix(in srgb, var(--accent-green) 10%, transparent)',
            border: `1px solid ${runStatus === 'error' ? 'color-mix(in srgb, var(--accent-red) 30%, transparent)' : 'color-mix(in srgb, var(--accent-green) 30%, transparent)'}`,
          }}
        >
          <AlertDescription style={{ fontSize: '0.8rem', color: runStatus === 'error' ? 'var(--accent-red)' : 'var(--accent-green)' }}>
            {runMessage}
          </AlertDescription>
        </Alert>
      )}

      {/* Two-column layout: step builder + preview */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '1rem', alignItems: 'start' }}>
        {/* Step list */}
        <div>
          {toolsLoading ? (
            <Skeleton style={{ height: '6rem', borderRadius: '0.5rem' }} />
          ) : steps.length === 0 ? (
            <div
              style={{
                padding: '2rem',
                textAlign: 'center',
                border: '2px dashed var(--border)',
                borderRadius: '0.5rem',
                color: 'var(--text-secondary)',
                fontSize: '0.875rem',
              }}
            >
              No steps yet. Click &quot;Add Step&quot; to start building.
            </div>
          ) : (
            steps.map((step, idx) => (
              <StepCard
                key={step.step_id}
                step={step}
                index={idx}
                total={steps.length}
                tools={tools}
                executionState={executionMap[step.step_id]}
                onChange={(updated) => updateStep(idx, updated)}
                onRemove={() => removeStep(idx)}
                onMoveUp={() => moveStep(idx, -1)}
                onMoveDown={() => moveStep(idx, 1)}
              />
            ))
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={addStep}
            style={{ marginTop: '0.5rem', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          >
            <Plus size={14} style={{ marginRight: '0.35rem' }} />
            Add Step
          </Button>
        </div>

        {/* Preview panel */}
        <div style={{ position: 'sticky', top: '1rem' }}>
          <Card style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
            <CardContent style={{ padding: '1rem' }}>
              <h3 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', color: 'var(--text-primary)' }}>
                Step Sequence
              </h3>
              {steps.length === 0 ? (
                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>No steps defined.</p>
              ) : (
                <ol style={{ paddingLeft: '1rem', margin: 0 }}>
                  {steps.map((step, idx) => {
                    const execState = executionMap[step.step_id]
                    return (
                      <li key={step.step_id} style={{ fontSize: '0.75rem', color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                          <code style={{ fontFamily: 'monospace', fontSize: '0.7rem' }}>
                            {step.tool_name || '(no tool)'}
                          </code>
                          {step.require_approval && (
                            <Badge
                              style={{
                                fontSize: '0.6rem',
                                background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
                                color: 'var(--accent-blue)',
                                border: '1px solid color-mix(in srgb, var(--accent-blue) 25%, transparent)',
                              }}
                            >
                              HITL
                            </Badge>
                          )}
                          {execState && <StepStatusBadge status={execState.status} />}
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', marginTop: '0.1rem' }}>
                          on_failure: {step.on_failure}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              )}

              {/* Run status indicator */}
              {runStatus !== 'idle' && (
                <div
                  style={{
                    marginTop: '0.75rem',
                    paddingTop: '0.75rem',
                    borderTop: '1px solid var(--border)',
                    fontSize: '0.75rem',
                  }}
                >
                  <span style={{ color: 'var(--text-secondary)' }}>Run status: </span>
                  <Badge
                    style={{
                      background: runStatus === 'running'
                        ? 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)'
                        : runStatus === 'complete'
                          ? 'color-mix(in srgb, var(--accent-green) 15%, transparent)'
                          : 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
                      color: runStatus === 'running'
                        ? 'var(--accent-yellow)'
                        : runStatus === 'complete'
                          ? 'var(--accent-green)'
                          : 'var(--accent-red)',
                      border: 'none',
                    }}
                  >
                    {runStatus}
                  </Badge>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
