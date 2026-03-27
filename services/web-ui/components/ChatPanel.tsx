'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Text, makeStyles, tokens } from '@fluentui/react-components';
import { ChatBubble } from './ChatBubble';
import { UserBubble } from './UserBubble';
import { ThinkingIndicator } from './ThinkingIndicator';
import { ChatInput } from './ChatInput';
import { ProposalCard } from './ProposalCard';
import { useSSE, SSEEvent } from '@/lib/use-sse';
import type { Message, ApprovalGateTracePayload } from '@/types/sse';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: tokens.spacingHorizontalL,
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
  },
});

interface ChatPanelProps {
  subscriptions: string[];
}

export function ChatPanel({ subscriptions }: ChatPanelProps) {
  const styles = useStyles();
  const [messages, setMessages] = useState<Message[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentAgent, setCurrentAgent] = useState('Orchestrator');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle token events — accumulate delta into streaming assistant message
  const handleTokenEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>;
    const delta = (data.delta as string) || '';
    const agent = (data.agent as string) || currentAgent;

    setCurrentAgent(agent);
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
  }, [currentAgent]);

  // Handle trace events — check for approval_gate type
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
            agentName: currentAgent,
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
  }, [currentAgent]);

  // Token SSE connection
  useSSE({
    threadId,
    streamType: 'token',
    onEvent: handleTokenEvent,
  });

  // Trace SSE connection
  useSSE({
    threadId,
    streamType: 'trace',
    onEvent: handleTraceEvent,
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
        // Start SSE connections if this is a new thread
        if (!threadId) {
          setThreadId(data.thread_id);
        }
      } else {
        setIsStreaming(false);
        setMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: 'assistant',
            agentName: 'System',
            content: 'Failed to send message. Please try again.',
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

  // Empty state when no messages
  if (messages.length === 0) {
    return (
      <div className={styles.root}>
        <div className={styles.emptyState}>
          <Text weight="semibold" size={400}>Start a conversation</Text>
          <Text align="center" size={300}>
            Ask about any Azure resource, investigate an incident, or check
            the status of your infrastructure. Type a message below to begin.
          </Text>
        </div>
        <ChatInput onSend={handleSubmit} disabled={isStreaming} />
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <div className={styles.messages} role="log" aria-live="polite">
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
          <ThinkingIndicator agentName={currentAgent} />
        )}
        <div ref={messagesEndRef} />
      </div>
      <ChatInput onSend={handleSubmit} disabled={isStreaming} />
    </div>
  );
}
