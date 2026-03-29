'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { MessageSquare } from 'lucide-react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { ChatBubble } from './ChatBubble';
import { UserBubble } from './UserBubble';
import { ThinkingIndicator } from './ThinkingIndicator';
import { ChatInput } from './ChatInput';
import { ProposalCard } from './ProposalCard';
import { useSSE, SSEEvent } from '@/lib/use-sse';
import type { Message, ApprovalGateTracePayload } from '@/types/sse';

const QUICK_EXAMPLES = [
  'Show my virtual machines',
  'List VMs with high CPU usage',
  'Are there any active alerts?',
  'Show unhealthy resources',
  'Which VMs are stopped?',
  'Check storage account health',
  'Summarize recent incidents',
];

interface ChatPanelProps {
  subscriptions: string[];
}

export function ChatPanel({ subscriptions }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [runKey, setRunKey] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const currentAgentRef = useRef('Orchestrator');

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleTokenEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>;
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
    currentAgentRef.current = agent;
    setMessages((prev) => {
      const lastMsg = prev[prev.length - 1];
      if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isStreaming) {
        return [
          ...prev.slice(0, -1),
          { ...lastMsg, content: lastMsg.content + delta, agentName: agent },
        ];
      }
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
  }, []);

  const handleTraceEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>;
    if (data.type === 'approval_gate') {
      const approvalGate = data as unknown as ApprovalGateTracePayload;
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          return [
            ...prev.slice(0, -1),
            { ...lastMsg, approvalGate, isStreaming: false },
          ];
        }
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

  useSSE({ threadId, runId, streamType: 'token', onEvent: handleTokenEvent, runKey });
  useSSE({ threadId, runId, streamType: 'trace', onEvent: handleTraceEvent, runKey });

  const handleSubmit = useCallback(async (message: string) => {
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
          setThreadId(data.thread_id);
        } else {
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

  const handleApprove = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      });
    } catch { /* Error handled by ProposalCard state */ }
  }, []);

  const handleReject = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      });
    } catch { /* Error handled by ProposalCard state */ }
  }, []);

  const ExampleChips = (
    <div className="flex flex-wrap gap-2 px-4 py-1">
      {QUICK_EXAMPLES.map((example) => (
        <Button
          key={example}
          variant="outline"
          size="sm"
          disabled={isStreaming}
          onClick={() => handleSubmit(example)}
          className="inline-flex items-center rounded-md border border-border px-2.5 py-1 text-xs font-semibold text-muted-foreground bg-background hover:bg-accent hover:text-accent-foreground disabled:opacity-50 disabled:pointer-events-none transition-colors cursor-pointer whitespace-nowrap h-auto"
        >
          {example}
        </Button>
      ))}
    </div>
  );

  if (messages.length === 0) {
    return (
      <div className="absolute inset-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center justify-center gap-4 px-4">
          <MessageSquare className="h-8 w-8 text-muted-foreground" />
          <h2 className="font-semibold text-lg">Start a conversation</h2>
          <p className="text-sm text-muted-foreground text-center max-w-md">
            Ask about any Azure resource, investigate an incident, or check the status of your infrastructure.
          </p>
          <div className="flex flex-wrap gap-2 justify-center max-w-[480px] mt-2">
            {QUICK_EXAMPLES.map((example) => (
              <Button
                key={example}
                variant="outline"
                size="sm"
                disabled={isStreaming}
                onClick={() => handleSubmit(example)}
                className="inline-flex items-center rounded-md border border-border px-2.5 py-1 text-xs font-semibold text-muted-foreground bg-background hover:bg-accent hover:text-accent-foreground disabled:opacity-50 disabled:pointer-events-none transition-colors cursor-pointer whitespace-nowrap h-auto"
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
        <div className="shrink-0 grow-0">
          {ExampleChips}
          <ChatInput onSend={handleSubmit} disabled={isStreaming} />
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 flex flex-col overflow-hidden">
      <ScrollArea className="flex-1 min-h-0">
        <div className="flex flex-col w-full px-4 py-4" role="log" aria-live="polite">
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
      </ScrollArea>
      <div className="shrink-0 grow-0">
        {ExampleChips}
        <ChatInput onSend={handleSubmit} disabled={isStreaming} />
      </div>
    </div>
  );
}
