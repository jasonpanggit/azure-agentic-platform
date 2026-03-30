/**
 * @jest-environment jsdom
 *
 * Tests for ChatPanel component (components/ChatPanel.tsx).
 * Replaces the empty Plan 05-01 stubs in layout.test.tsx.
 *
 * ChatPanel is a complex streaming component. We mock its external
 * dependencies (useSSE, fetch, UI library components) so tests focus
 * on the component's own rendering logic and state behaviour.
 */
import { describe, it, expect, jest, beforeEach, afterEach } from '@jest/globals';
import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

// ---------------------------------------------------------------------------
// jsdom doesn't implement scrollIntoView — polyfill it so ChatPanel's
// messagesEndRef.scrollIntoView({ behavior: 'smooth' }) doesn't throw.
// ---------------------------------------------------------------------------
Element.prototype.scrollIntoView = jest.fn();

// ---------------------------------------------------------------------------
// Mock heavy external dependencies before importing the component.
// ---------------------------------------------------------------------------

// useSSE — suppress real EventSource connections; expose a handle so tests can
// fire synthetic events if needed (not required for rendering tests).
jest.mock('@/lib/use-sse', () => ({
  useSSE: jest.fn(() => ({ connected: false, reconnecting: false, lastSeq: 0 })),
}));

// Radix ScrollArea — render children directly so we can find them in DOM.
jest.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-testid': 'scroll-area' }, children),
}));

// Button — thin wrapper that passes through onClick and disabled.
jest.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, disabled, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children?: React.ReactNode }) =>
    React.createElement('button', { onClick, disabled, ...rest }, children),
}));

// Textarea — render as a plain textarea so we can type into it.
jest.mock('@/components/ui/textarea', () => ({
  Textarea: React.forwardRef(
    (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>, ref: React.ForwardedRef<HTMLTextAreaElement>) =>
      React.createElement('textarea', { ...props, ref })
  ),
}));

// lucide-react icons — render as empty spans to avoid SVG complexity.
jest.mock('lucide-react', () => ({
  MessageSquare: () => React.createElement('span', { 'data-testid': 'icon-message-square' }),
  Send: () => React.createElement('span', { 'data-testid': 'icon-send' }),
}));

// Sub-components that render message bubbles — simple pass-through stubs.
jest.mock('@/components/ChatBubble', () => ({
  ChatBubble: ({ content, agentName }: { content: string; agentName: string }) =>
    React.createElement('div', { 'data-testid': 'chat-bubble', 'data-agent': agentName }, content),
}));

jest.mock('@/components/UserBubble', () => ({
  UserBubble: ({ content }: { content: string }) =>
    React.createElement('div', { 'data-testid': 'user-bubble' }, content),
}));

jest.mock('@/components/ThinkingIndicator', () => ({
  ThinkingIndicator: ({ agentName }: { agentName: string }) =>
    React.createElement('div', { 'data-testid': 'thinking-indicator', 'data-agent': agentName }),
}));

jest.mock('@/components/ProposalCard', () => ({
  ProposalCard: ({ approval }: { approval: { id: string } }) =>
    React.createElement('div', { 'data-testid': 'proposal-card', 'data-approval-id': approval.id }),
}));

jest.mock('@/components/ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (msg: string) => void; disabled: boolean }) =>
    React.createElement('div', { 'data-testid': 'chat-input', 'data-disabled': String(disabled) },
      React.createElement('input', {
        'data-testid': 'chat-input-field',
        placeholder: 'Ask about any Azure resource...',
        onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => {
          if (e.key === 'Enter') {
            onSend((e.currentTarget as HTMLInputElement).value);
          }
        },
      })
    ),
}));

// ---------------------------------------------------------------------------
// Now import the component under test.
// ---------------------------------------------------------------------------
import { ChatPanel } from '../components/ChatPanel';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderChatPanel(subscriptions: string[] = []) {
  return render(React.createElement(ChatPanel, { subscriptions }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ChatPanel', () => {
  let fetchSpy: jest.MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchSpy = jest.fn() as jest.MockedFunction<typeof fetch>;
    global.fetch = fetchSpy as unknown as typeof fetch;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  describe('empty state (no messages)', () => {
    it('renders the "Start a conversation" heading', () => {
      renderChatPanel();
      expect(screen.getByText('Start a conversation')).toBeInTheDocument();
    });

    it('renders the MessageSquare icon in the empty state', () => {
      renderChatPanel();
      expect(screen.getByTestId('icon-message-square')).toBeInTheDocument();
    });

    it('renders the descriptive prompt text', () => {
      renderChatPanel();
      expect(
        screen.getByText(/Ask about any Azure resource/i)
      ).toBeInTheDocument();
    });

    it('renders quick-example buttons', () => {
      renderChatPanel();
      // There are QUICK_EXAMPLES — at least one visible button for examples.
      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('renders the ChatInput in empty state', () => {
      renderChatPanel();
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  describe('after a message is sent', () => {
    it('calls fetch /api/proxy/chat on submit', async () => {
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: 'th_abc', run_id: 'run_xyz' }),
      } as Response);

      renderChatPanel(['sub-1']);

      const inputField = screen.getByTestId('chat-input-field');
      // Set the value and press Enter to trigger onSend
      Object.defineProperty(inputField, 'value', { value: 'Show my VMs', configurable: true });
      await act(async () => {
        fireEvent.keyDown(inputField, { key: 'Enter', target: { value: 'Show my VMs' } });
      });

      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          '/api/proxy/chat',
          expect.objectContaining({ method: 'POST' })
        );
      });
    });

    it('sends subscription_ids in the request body', async () => {
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: 'th_abc', run_id: 'run_xyz' }),
      } as Response);

      renderChatPanel(['sub-1', 'sub-2']);

      const inputField = screen.getByTestId('chat-input-field');
      Object.defineProperty(inputField, 'value', { value: 'List VMs', configurable: true });
      await act(async () => {
        fireEvent.keyDown(inputField, { key: 'Enter', target: { value: 'List VMs' } });
      });

      await waitFor(() => {
        const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
        const body = JSON.parse(init.body as string) as { subscription_ids: string[] };
        expect(body.subscription_ids).toEqual(['sub-1', 'sub-2']);
      });
    });

    it('displays the user message in the log after submit', async () => {
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: 'th_abc', run_id: 'run_xyz' }),
      } as Response);

      renderChatPanel();

      const inputField = screen.getByTestId('chat-input-field');
      Object.defineProperty(inputField, 'value', { value: 'Hello agent', configurable: true });
      await act(async () => {
        fireEvent.keyDown(inputField, { key: 'Enter', target: { value: 'Hello agent' } });
      });

      await waitFor(() => {
        expect(screen.getByTestId('user-bubble')).toBeInTheDocument();
        expect(screen.getByTestId('user-bubble')).toHaveTextContent('Hello agent');
      });
    });

    it('renders message log with role="log" aria-live="polite"', async () => {
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: 'th_abc', run_id: 'run_xyz' }),
      } as Response);

      renderChatPanel();

      const inputField = screen.getByTestId('chat-input-field');
      Object.defineProperty(inputField, 'value', { value: 'Hello', configurable: true });
      await act(async () => {
        fireEvent.keyDown(inputField, { key: 'Enter', target: { value: 'Hello' } });
      });

      await waitFor(() => {
        const log = screen.getByRole('log');
        expect(log).toBeInTheDocument();
        expect(log).toHaveAttribute('aria-live', 'polite');
      });
    });
  });

  // -------------------------------------------------------------------------
  describe('network error handling', () => {
    it('shows a "Network error" assistant message when fetch throws', async () => {
      fetchSpy.mockRejectedValueOnce(new Error('Network failure'));

      renderChatPanel();

      const inputField = screen.getByTestId('chat-input-field');
      Object.defineProperty(inputField, 'value', { value: 'Test message', configurable: true });
      await act(async () => {
        fireEvent.keyDown(inputField, { key: 'Enter', target: { value: 'Test message' } });
      });

      await waitFor(() => {
        expect(screen.getByText(/Network error/i)).toBeInTheDocument();
      });
    });

    it('shows an API error message when fetch returns non-ok response', async () => {
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ error: 'Service unavailable' }),
      } as Response);

      renderChatPanel();

      const inputField = screen.getByTestId('chat-input-field');
      Object.defineProperty(inputField, 'value', { value: 'Another message', configurable: true });
      await act(async () => {
        fireEvent.keyDown(inputField, { key: 'Enter', target: { value: 'Another message' } });
      });

      await waitFor(() => {
        expect(screen.getByText('Service unavailable')).toBeInTheDocument();
      });
    });
  });

  // -------------------------------------------------------------------------
  describe('quick example chips', () => {
    it('clicking a quick example chip submits that text as a message', async () => {
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ thread_id: 'th_1', run_id: 'run_1' }),
      } as Response);

      renderChatPanel();

      // Find the first quick example button (empty state renders them)
      const firstChip = screen.getAllByRole('button')[0];
      const chipText = firstChip.textContent ?? '';
      expect(chipText.length).toBeGreaterThan(0);

      await act(async () => {
        fireEvent.click(firstChip);
      });

      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          '/api/proxy/chat',
          expect.objectContaining({
            body: expect.stringContaining(chipText),
          })
        );
      });
    });
  });
});
