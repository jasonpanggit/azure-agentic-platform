/**
 * SSE event type definitions for the Web UI.
 *
 * These types define the shape of events emitted by the /api/stream Route Handler
 * and consumed by the useSSE hook and ChatPanel. The approval_gate trace event
 * is emitted by the Python SSE route when an agent proposes a remediation action
 * requiring human approval.
 */

/** Base SSE event fields present in all events. */
export interface BaseSSEEvent {
  seq: number;
  thread_id: string;
}

/** Token event — streaming text content from an agent. */
export interface TokenEvent extends BaseSSEEvent {
  type: 'token';
  delta: string;
  agent: string;
}

/** Trace event — agent tool calls, handoffs, and approval gates. */
export interface TraceEvent extends BaseSSEEvent {
  type: 'tool_call' | 'handoff' | 'approval_gate' | 'error';
  name: string;
  status: 'success' | 'error' | 'pending';
  durationMs?: number;
  payload: Record<string, unknown>;
}

/**
 * Approval gate trace event payload.
 *
 * Emitted as `event:trace` with `type: 'approval_gate'` when an agent
 * proposes a remediation action requiring HITL approval. The ChatPanel
 * uses this to render a ProposalCard inline in the conversation.
 */
export interface ApprovalGateTracePayload {
  type: 'approval_gate';
  approval_id: string;
  thread_id: string;
  action_id: string;
  proposal: {
    description: string;
    risk_level: 'low' | 'medium' | 'high' | 'critical';
    target_resources: string[];
    estimated_impact: string;
  };
  expires_at: string; // ISO 8601
  seq: number;
}

/** Done event — signals the end of the SSE stream for a thread. */
export interface DoneEvent extends BaseSSEEvent {
  type: 'done';
}

/** Error event — signals an error in the SSE stream. */
export interface ErrorEvent extends BaseSSEEvent {
  type: 'error';
  message: string;
  code?: string;
}

/** Union type for all SSE events. */
export type SSEEventData = TokenEvent | TraceEvent | DoneEvent | ErrorEvent;

/**
 * Chat message type used by ChatPanel state.
 */
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  agentName?: string;
  content: string;
  isStreaming?: boolean;
  approvalGate?: ApprovalGateTracePayload;
  timestamp: string;
}
