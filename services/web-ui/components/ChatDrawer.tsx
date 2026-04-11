'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useResizable } from '@/lib/use-resizable'
import { MessageSquare, X } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useSSE, SSEEvent } from '@/lib/use-sse'
import { useAppState } from '@/lib/app-state-context'
import { gatewayTokenRequest } from '@/lib/msal-config'
import type { ApprovalGateTracePayload } from '@/types/sse'
import { ChatBubble } from './ChatBubble'
import { UserBubble } from './UserBubble'
import { ChatInput } from './ChatInput'
import { ThinkingIndicator } from './ThinkingIndicator'
import { ProposalCard } from './ProposalCard'
import { VerificationCard } from './VerificationCard'
import { useVerificationPoll } from '@/lib/use-verification-poll'

const QUICK_EXAMPLES = [
  'Show my virtual machines',
  'List VMs with high CPU usage',
  'Are there any active alerts?',
  'Show unhealthy resources',
  'Which VMs are stopped?',
  'Check storage account health',
  'Summarize recent incidents',
]

export function ChatDrawer() {
  const { instance, accounts } = useMsal()
  const { width, onMouseDown } = useResizable()
  const {
    drawerOpen, setDrawerOpen,
    messages, setMessages,
    isStreaming, setIsStreaming,
    threadId, setThreadId,
    runId, setRunId,
    runKey, setRunKey,
    currentAgentRef,
    input, setInput,
    selectedSubscriptions,
  } = useAppState()

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const account = accounts[0]
    if (!account) return null
    try {
      const result = await instance.acquireTokenSilent({ ...gatewayTokenRequest, account })
      return result.accessToken
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        // Token expired or consent needed — redirect to login
        await instance.acquireTokenRedirect({ ...gatewayTokenRequest, account })
      }
      return null
    }
  }, [instance, accounts])

  // ── Verification tracking (LOOP-002) ──
  const [executedApproval, setExecutedApproval] = useState<{
    approvalId: string;
    incidentId: string;
    executedAt: string;
    action: string;
    resourceIds: string[];
  } | null>(null)

  const { result: verificationResult, isPolling: isVerificationPolling } = useVerificationPoll({
    approvalId: executedApproval?.approvalId ?? null,
    executedAt: executedApproval?.executedAt ?? null,
    delayMinutes: 5,
    getAccessToken,
  })

  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── SSE: token stream ──
  const handleTokenEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>
    if (data.type === 'done') {
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.isStreaming) return [...prev.slice(0, -1), { ...last, isStreaming: false }]
        return prev
      })
      setIsStreaming(false)
      return
    }
    const delta = (data.delta as string) || ''
    const agent = (data.agent as string) || currentAgentRef.current
    currentAgentRef.current = agent
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.role === 'assistant' && last.isStreaming) {
        return [...prev.slice(0, -1), { ...last, content: last.content + delta, agentName: agent }]
      }
      return [...prev, {
        id: `msg-${event.seq}`,
        role: 'assistant' as const,
        agentName: agent,
        content: delta,
        isStreaming: true,
        timestamp: new Date().toLocaleTimeString(),
      }]
    })
  }, [setMessages, setIsStreaming, currentAgentRef])

  // ── SSE: trace stream ──
  const handleTraceEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>
    if (data.type === 'approval_gate') {
      const approvalGate = data as unknown as ApprovalGateTracePayload
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.role === 'assistant') {
          return [...prev.slice(0, -1), { ...last, approvalGate, isStreaming: false }]
        }
        return [...prev, {
          id: `msg-gate-${event.seq}`,
          role: 'assistant' as const,
          agentName: currentAgentRef.current,
          content: 'A remediation action requires your approval:',
          isStreaming: false,
          approvalGate,
          timestamp: new Date().toLocaleTimeString(),
        }]
      })
      setIsStreaming(false)
    }
    if (data.type === 'done') {
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.isStreaming) return [...prev.slice(0, -1), { ...last, isStreaming: false }]
        return prev
      })
      setIsStreaming(false)
    }
  }, [setMessages, setIsStreaming, currentAgentRef])

  useSSE({ threadId, runId, streamType: 'token', onEvent: handleTokenEvent, runKey })
  useSSE({ threadId, runId, streamType: 'trace', onEvent: handleTraceEvent, runKey })

  // ── Send message ──
  const handleSend = useCallback(async (messageOverride?: string) => {
    const message = (messageOverride ?? input).trim()
    if (!message || isStreaming) return
    setInput('')
    setMessages((prev) => [...prev, {
      id: crypto.randomUUID(),
      role: 'user',
      content: message,
      timestamp: new Date().toLocaleTimeString(),
    }])
    setIsStreaming(true)
    try {
      const token = await getAccessToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch('/api/proxy/chat', {
        method: 'POST',
        headers,
        body: JSON.stringify({ message, thread_id: threadId, subscription_ids: selectedSubscriptions }),
      })
      if (res.ok) {
        const data = await res.json()
        setRunId(data.run_id ?? null)
        if (!threadId) { setThreadId(data.thread_id) }
        else { setRunKey((k) => k + 1) }
      } else {
        const data = await res.json().catch(() => ({}))
        const errorMsg = (data as { error?: string }).error ?? `Request failed (${res.status})`
        setIsStreaming(false)
        setMessages((prev) => [...prev, {
          id: crypto.randomUUID(),
          role: 'assistant',
          agentName: 'System',
          content: errorMsg,
          isStreaming: false,
          timestamp: new Date().toLocaleTimeString(),
        }])
      }
    } catch {
      setIsStreaming(false)
      setMessages((prev) => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        agentName: 'System',
        content: 'Network error. Please check your connection.',
        isStreaming: false,
        timestamp: new Date().toLocaleTimeString(),
      }])
    }
  }, [input, isStreaming, threadId, selectedSubscriptions, getAccessToken, setInput, setMessages, setIsStreaming, setRunId, setThreadId, setRunKey])

  // ── Approvals ──
  const handleApprove = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      })
      // Track for verification polling (LOOP-002)
      // Find the approval gate context from the messages state
      const approvalMsg = messages.find(m => m.approvalGate?.approval_id === approvalId)
      const gate = approvalMsg?.approvalGate
      if (gate) {
        setExecutedApproval({
          approvalId: gate.approval_id,
          incidentId: gate.action_id,
          executedAt: new Date().toISOString(),
          action: gate.proposal.description,
          resourceIds: gate.proposal.target_resources,
        })
      }
    } catch { /* ProposalCard handles its own error state */ }
  }, [messages])

  const handleReject = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      })
    } catch { /* ProposalCard handles its own error state */ }
  }, [])

  // ── Verification re-diagnosis handler (LOOP-005) ──
  // Delegates to handleSend with a message override so the re-diagnosis
  // message is injected into the existing Foundry thread (via thread_id in
  // the chat proxy request body) rather than creating an orphan thread.
  const handleVerificationChatMessage = useCallback((message: string) => {
    handleSend(message)
  }, [handleSend])

  return (
    <>
      {/* Backdrop */}
      {drawerOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 transition-opacity"
          style={{ top: '48px' }}
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* Drawer panel */}
      <div
        className="fixed left-0 flex flex-col transition-transform duration-300 ease-out"
        style={{
          top: '48px',
          width: `${width}px`,
          height: 'calc(100vh - 48px)',
          zIndex: 45,
          background: 'var(--bg-surface)',
          borderRight: '1px solid var(--border)',
          boxShadow: '4px 0 24px rgba(0,0,0,0.25)',
          transform: drawerOpen ? 'translateX(0)' : 'translateX(-100%)',
        }}
      >
        {/* Resize handle */}
        <div
          onMouseDown={onMouseDown}
          className="absolute right-0 top-0 h-full w-2 cursor-col-resize group z-10 hover:bg-blue-500/20 transition-colors"
          title="Drag to resize"
        />

        {/* Header */}
        <div
          className="flex items-center justify-between px-4 flex-shrink-0"
          style={{ height: '48px', background: 'var(--bg-surface-raised)', borderBottom: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: 'var(--accent-green)' }} />
            <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Azure AI</span>
          </div>
          <span
            className="text-[11px] px-2 py-0.5 rounded font-mono"
            style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
          >
            GPT-4o
          </span>
          <button
            onClick={() => setDrawerOpen(false)}
            className="w-7 h-7 flex items-center justify-center rounded transition-colors"
            style={{ color: 'var(--text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--text-primary)'
              e.currentTarget.style.background = 'var(--bg-subtle)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-muted)'
              e.currentTarget.style.background = 'transparent'
            }}
            aria-label="Close chat"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Message area or empty state */}
        {messages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 gap-4">
            <MessageSquare className="h-12 w-12" style={{ color: 'var(--text-muted)' }} />
            <p className="text-sm text-center" style={{ color: 'var(--text-secondary)' }}>
              Ask anything about your Azure infrastructure
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {QUICK_EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => setInput(ex)}
                  className="text-xs px-3 py-1.5 rounded-md transition-colors"
                  style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'color-mix(in srgb, var(--accent-blue) 10%, transparent)'
                    e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--accent-blue) 40%, transparent)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'var(--bg-subtle)'
                    e.currentTarget.style.borderColor = 'var(--border)'
                  }}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ScrollArea className="flex-1 px-4 py-3">
            <div role="log" aria-live="polite" className="flex flex-col">
              {messages.map((msg) => (
                msg.role === 'user' ? (
                  <UserBubble key={msg.id} content={msg.content} timestamp={msg.timestamp} />
                ) : (
                  <div key={msg.id}>
                    <ChatBubble
                      agentName={msg.agentName || 'Agent'}
                      content={msg.content}
                      isStreaming={msg.isStreaming || false}
                      timestamp={msg.timestamp}
                      isError={msg.agentName === 'System'}
                    />
                    {msg.approvalGate && (
                      <ProposalCard
                        approval={{
                          id: msg.approvalGate.approval_id,
                          status: 'pending',
                          risk_level: msg.approvalGate.proposal.risk_level,
                          expires_at: msg.approvalGate.expires_at,
                          proposal: {
                            description: msg.approvalGate.proposal.description,
                            target_resources: msg.approvalGate.proposal.target_resources,
                            estimated_impact: msg.approvalGate.proposal.estimated_impact,
                            reversibility: 'unknown',
                          },
                        }}
                        onApprove={() => handleApprove(msg.approvalGate!.approval_id)}
                        onReject={() => handleReject(msg.approvalGate!.approval_id)}
                      />
                    )}
                  </div>
                )
              ))}
              {isStreaming && !messages[messages.length - 1]?.isStreaming && <ThinkingIndicator />}
              {executedApproval && (
                <VerificationCard
                  approvalId={executedApproval.approvalId}
                  incidentId={executedApproval.incidentId}
                  threadId={threadId || ''}
                  verificationResult={verificationResult?.verification_result ?? null}
                  isPolling={isVerificationPolling}
                  proposedAction={executedApproval.action}
                  resourceId={executedApproval.resourceIds?.[0] || ''}
                  rolledBack={verificationResult?.rolled_back}
                  getAccessToken={getAccessToken}
                  onChatMessage={handleVerificationChatMessage}
                />
              )}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>
        )}

        {/* Quick chips bar (only when conversation active) */}
        {messages.length > 0 && (
          <div
            className="flex items-center gap-2 px-4 overflow-x-auto flex-shrink-0"
            style={{ height: '40px', borderTop: '1px solid var(--border)' }}
          >
            {QUICK_EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setInput(ex)}
                className="text-xs px-3 py-1 rounded-md whitespace-nowrap flex-shrink-0 font-medium transition-colors"
                style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={handleSend}
          disabled={isStreaming}
        />
      </div>
    </>
  )
}
