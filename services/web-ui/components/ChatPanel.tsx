'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Text, Button, makeStyles, tokens } from '@fluentui/react-components';
import { ChatRegular } from '@fluentui/react-icons';
import { ChatBubble } from './ChatBubble';
import { UserBubble } from './UserBubble';
import { ThinkingIndicator } from './ThinkingIndicator';
import { ChatInput } from './ChatInput';
import { ProposalCard } from './ProposalCard';
import { useSSE, SSEEvent } from '@/lib/use-sse';
import type { Message, ApprovalGateTracePayload } from '@/types/sse';

/** Example prompts shown above the input field to guide operators. */
const QUICK_EXAMPLES = [
  'Show my virtual machines',
  'List VMs with high CPU usage',
  'Are there any active alerts?',
  'Show unhealthy resources',
  'Which VMs are stopped?',
  'Check storage account health',
  'Summarize recent incidents',
];

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    minHeight: 0,
    flex: '1 1 0',
    overflow: 'hidden',
  },
  messages: {
    flex: 1,
    minHeight: 0,
    padding: tokens.spacingHorizontalL,
    paddingBottom: tokens.spacingVerticalL,
    display: 'flex',
    flexDirection: 'column',
  },
  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: tokens.spacingVerticalM,
    padding: tokens.spacingHorizontalL,
  },
  emptyIcon: {
    fontSize: '32px',
    color: tokens.colorNeutralForeground3,
  },
  // Quick example chips row
  examplesRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalS,
    padding: `0 ${tokens.spacingHorizontalL} ${tokens.spacingVerticalS}`,
  },
  exampleChip: {
    borderRadius: tokens.borderRadiusMedium,
    fontSize: tokens.fontSizeBase200,
    height: '28px',
    whiteSpace: 'nowrap',
  },
  // Compact chips shown in the empty-state hero
  emptyExamplesRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalS,
    justifyContent: 'center',
    maxWidth: '480px',
    marginTop: tokens.spacingVerticalS,
  },
  inputArea: {
    display: 'flex',
    flexDirection: 'column',
  },
});

interface ChatPanelProps {
  subscriptions: string[];
}

export function ChatPanel({ subscriptions }: ChatPanelProps) {
  const styles = useStyles();
  const [messages, setMessages] = useState<Message[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [runKey, setRunKey] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Use a ref for currentAgent so that updating it does NOT recreate handleTokenEvent
  // (avoids the SSE reconnect-mid-stream bug that caused duplicate responses).
  const currentAgentRef = useRef('Orchestrator');

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle token events — accumulate delta into streaming assistant message.
  // IMPORTANT: no state variables in deps — only stable refs and setters.
  const handleTokenEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>;

    // Done event — finalize streaming message and clear spinner
    if (data.type === 'done') {
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.isStreaming) {
          return [...prev.slice(0, -1), { ...lastMsg, isStreaming: false }];
        }
        return prev;
      });
      setIsStreaming(false);
      return;
    }

    const delta = (data.delta as string) || '';
    const agent = (data.agent as string) || currentAgentRef.current;

    // Update ref (no re-render, no dep-change, no reconnect)
    currentAgentRef.current = agent;

    setMessages((prev) => {
      const lastMsg = prev[prev.length - 1];
      if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isStreaming) {
        // Append delta to existing streaming message (immutable update)
        return [
          ...prev.slice(0, -1),
          { ...lastMsg, content: lastMsg.content + delta, agentName: agent },
        ];
      }
      // Start a new streaming assistant message
      return [
        ...prev,
        {
          id: `msg-${event.seq}`,
          role: 'assistant' as const,
          agentName: agent,
          content: delta,
          isStreaming: true,
          timestamp: new Date().toLocaleTimeString(),
        },
      ];
    });
  // No state deps — currentAgentRef is a ref (stable), setMessages/setIsStreaming are stable setters
  }, []);

  // Handle trace events — check for approval_gate type.
  // Same pattern: use currentAgentRef instead of state to avoid spurious reconnects.
  const handleTraceEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>;

    if (data.type === 'approval_gate') {
      const approvalGate = data as unknown as ApprovalGateTracePayload;
      // Set approvalGate field on the last assistant message
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          return [
            ...prev.slice(0, -1),
            { ...lastMsg, approvalGate, isStreaming: false },
          ];
        }
        // If no assistant message exists, create one with the approval gate
        return [
          ...prev,
          {
            id: `msg-gate-${event.seq}`,
            role: 'assistant' as const,
            agentName: currentAgentRef.current,
            content: 'A remediation action requires your approval:',
            isStreaming: false,
            approvalGate,
            timestamp: new Date().toLocaleTimeString(),
          },
        ];
      });
      setIsStreaming(false);
    }

    if (data.type === 'done') {
      // Mark last streaming message as complete
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.isStreaming) {
          return [
            ...prev.slice(0, -1),
            { ...lastMsg, isStreaming: false },
          ];
        }
        return prev;
      });
      setIsStreaming(false);
    }
  }, []);

  // Token SSE connection
  useSSE({
    threadId,
    runId,
    streamType: 'token',
    onEvent: handleTokenEvent,
    runKey,
  });

  // Trace SSE connection
  useSSE({
    threadId,
    runId,
    streamType: 'trace',
    onEvent: handleTraceEvent,
    runKey,
  });

  // Submit a chat message
  const handleSubmit = useCallback(async (message: string) => {
    // Add user message to conversation
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    try {
      const res = await fetch('/api/proxy/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          thread_id: threadId,
          subscription_ids: subscriptions,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setRunId(data.run_id ?? null);
        if (!threadId) {
          // First message — set threadId (triggers SSE connection)
          setThreadId(data.thread_id);
        } else {
          // Subsequent messages on same thread — bump runKey to reopen SSE
          setRunKey((k) => k + 1);
        }
      } else {
        const data = await res.json().catch(() => ({}));
        const errorMsg = (data as { error?: string }).error ?? `Request failed (${res.status})`;
        setIsStreaming(false);
        setMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: 'assistant',
            agentName: 'System',
            content: errorMsg,
            isStreaming: false,
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
      }
    } catch {
      setIsStreaming(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          agentName: 'System',
          content: 'Network error. Please check your connection.',
          isStreaming: false,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    }
  }, [threadId, subscriptions]);

  // Handle approval actions
  const handleApprove = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      });
    } catch {
      // Error handled by ProposalCard state
    }
  }, []);

  const handleReject = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      });
    } catch {
      // Error handled by ProposalCard state
    }
  }, []);

  /** Quick example chip row — reused in both empty state and active chat. */
  const ExampleChips = (
    <div className={styles.examplesRow}>
      {QUICK_EXAMPLES.map((example) => (
        <Button
          key={example}
          size="small"
          shape="rounded"
          appearance="outline"
          className={styles.exampleChip}
          disabled={isStreaming}
          onClick={() => handleSubmit(example)}
        >
          {example}
        </Button>
      ))}
    </div>
  );

  // Empty state when no messages
  if (messages.length === 0) {
    return (
      <div className={styles.root}>
        <div className={styles.emptyState}>
          <ChatRegular className={styles.emptyIcon} />
          <Text weight="semibold" size={400}>Start a conversation</Text>
          <Text align="center" size={300}>
            Ask about any Azure resource, investigate an incident, or check
            the status of your infrastructure.
          </Text>
          <div className={styles.emptyExamplesRow}>
            {QUICK_EXAMPLES.map((example) => (
              <Button
                key={example}
                size="small"
                shape="rounded"
                appearance="outline"
                className={styles.exampleChip}
                disabled={isStreaming}
                onClick={() => handleSubmit(example)}
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
        <div className={styles.inputArea}>
          {ExampleChips}
          <ChatInput onSend={handleSubmit} disabled={isStreaming} />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <div className={styles.messages} style={{ overflowY: 'auto', overflowX: 'hidden' }} role="log" aria-live="polite">
        {messages.map((msg) => (
          <React.Fragment key={msg.id}>
            {msg.role === 'user' ? (
              <UserBubble content={msg.content} timestamp={msg.timestamp} />
            ) : (
              <>
                <ChatBubble
                  agentName={msg.agentName || 'Agent'}
                  content={msg.content}
                  isStreaming={msg.isStreaming || false}
                  timestamp={msg.timestamp}
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
              </>
            )}
          </React.Fragment>
        ))}
        {isStreaming && !messages[messages.length - 1]?.isStreaming && (
          <ThinkingIndicator agentName={currentAgentRef.current} />
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className={styles.inputArea}>
        {ExampleChips}
        <ChatInput onSend={handleSubmit} disabled={isStreaming} />
      </div>
    </div>
  );
}
