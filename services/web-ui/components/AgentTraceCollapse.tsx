'use client'

import React, { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { ChevronDown, ChevronRight, Clock, Wrench, MessageSquare } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ToolCall {
  id: string
  type: string
  name: string
  arguments: string
  output?: string | null
  duration_ms?: number | null
}

export interface TraceStep {
  step_id: string
  type: string
  status: string
  created_at?: string | null
  tool_calls: ToolCall[]
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

interface AgentTraceCollapseProps {
  steps: TraceStep[]
  tokenUsage?: TokenUsage
  durationMs?: number | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function prettyJson(raw: string | null | undefined): string {
  if (!raw) return ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function StepTypeBadge({ type }: { type: string }) {
  const isToolCall = type === 'tool_calls'
  const style: React.CSSProperties = isToolCall
    ? {
        background: 'color-mix(in srgb, var(--accent-blue) 15%, transparent)',
        color: 'var(--accent-blue)',
        border: '1px solid color-mix(in srgb, var(--accent-blue) 30%, transparent)',
      }
    : {
        background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)',
        color: 'var(--accent-green)',
        border: '1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)',
      }
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
      style={style}
    >
      {isToolCall ? <Wrench className="w-3 h-3" /> : <MessageSquare className="w-3 h-3" />}
      {type === 'tool_calls' ? 'tool_calls' : 'message_creation'}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    completed: 'var(--accent-green)',
    in_progress: 'var(--accent-blue)',
    failed: 'var(--accent-red)',
    cancelled: 'var(--accent-yellow)',
    expired: 'var(--accent-yellow)',
  }
  const color = colorMap[status] ?? 'var(--text-secondary)'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {status}
    </span>
  )
}

function ToolCallRow({ call }: { call: ToolCall }) {
  const [argsOpen, setArgsOpen] = useState(false)
  const [outputOpen, setOutputOpen] = useState(false)

  return (
    <div
      className="rounded border text-xs"
      style={{ borderColor: 'var(--border)', background: 'var(--bg-surface)' }}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 flex-wrap">
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono font-medium"
          style={{
            background: 'color-mix(in srgb, var(--accent-purple) 15%, transparent)',
            color: 'var(--accent-purple)',
            border: '1px solid color-mix(in srgb, var(--accent-purple) 30%, transparent)',
          }}
        >
          <Wrench className="w-3 h-3" />
          {call.name || '(unknown)'}
        </span>
        {call.duration_ms != null && (
          <span className="flex items-center gap-1" style={{ color: 'var(--text-secondary)' }}>
            <Clock className="w-3 h-3" />
            {call.duration_ms.toFixed(0)} ms
          </span>
        )}
        <span className="ml-auto flex gap-2">
          {call.arguments && (
            <button
              onClick={() => setArgsOpen(o => !o)}
              className="flex items-center gap-1 hover:opacity-75 transition-opacity"
              style={{ color: 'var(--text-secondary)' }}
            >
              {argsOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              args
            </button>
          )}
          {call.output != null && (
            <button
              onClick={() => setOutputOpen(o => !o)}
              className="flex items-center gap-1 hover:opacity-75 transition-opacity"
              style={{ color: 'var(--text-secondary)' }}
            >
              {outputOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              output
            </button>
          )}
        </span>
      </div>

      {/* Arguments */}
      {argsOpen && call.arguments && (
        <pre
          className="px-3 pb-2 overflow-x-auto text-xs font-mono"
          style={{ color: 'var(--text-primary)', borderTop: '1px solid var(--border)' }}
        >
          {prettyJson(call.arguments)}
        </pre>
      )}

      {/* Output */}
      {outputOpen && call.output != null && (
        <pre
          className="px-3 pb-2 overflow-x-auto text-xs font-mono"
          style={{ color: 'var(--text-primary)', borderTop: '1px solid var(--border)' }}
        >
          {prettyJson(call.output)}
        </pre>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AgentTraceCollapse({ steps, tokenUsage, durationMs }: AgentTraceCollapseProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())

  const toggleStep = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) next.delete(stepId)
      else next.add(stepId)
      return next
    })
  }

  return (
    <div className="space-y-2 py-2">
      {/* Summary row */}
      <div className="flex flex-wrap items-center gap-3 px-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
        {durationMs != null && (
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {(durationMs / 1000).toFixed(2)}s total
          </span>
        )}
        {tokenUsage && tokenUsage.total_tokens > 0 && (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
              color: 'var(--accent-blue)',
            }}
          >
            {tokenUsage.total_tokens.toLocaleString()} tokens
          </span>
        )}
        <span>{steps.length} step{steps.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Steps */}
      {steps.length === 0 && (
        <p className="text-xs px-1" style={{ color: 'var(--text-secondary)' }}>
          No steps recorded for this run.
        </p>
      )}

      {steps.map((step, idx) => {
        const isExpanded = expandedSteps.has(step.step_id)
        const hasToolCalls = step.type === 'tool_calls' && step.tool_calls.length > 0
        return (
          <div
            key={step.step_id}
            className="rounded border"
            style={{ borderColor: 'var(--border)', background: 'var(--bg-canvas)' }}
          >
            {/* Step header */}
            <button
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:opacity-80 transition-opacity"
              onClick={() => hasToolCalls && toggleStep(step.step_id)}
              style={{ cursor: hasToolCalls ? 'pointer' : 'default' }}
            >
              <span style={{ color: 'var(--text-secondary)', minWidth: '1.2rem' }}>{idx + 1}.</span>
              <StepTypeBadge type={step.type} />
              <StatusBadge status={step.status} />
              {hasToolCalls && (
                <span style={{ color: 'var(--text-secondary)' }}>
                  {step.tool_calls.length} call{step.tool_calls.length !== 1 ? 's' : ''}
                </span>
              )}
              {hasToolCalls && (
                <span className="ml-auto" style={{ color: 'var(--text-secondary)' }}>
                  {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                </span>
              )}
            </button>

            {/* Tool calls */}
            {isExpanded && hasToolCalls && (
              <div
                className="px-3 pb-3 space-y-2"
                style={{ borderTop: '1px solid var(--border)' }}
              >
                {step.tool_calls.map(tc => (
                  <ToolCallRow key={tc.id} call={tc} />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
