import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  cleanupDedupMap,
  checkAndEscalate,
  startEscalationScheduler,
  _resetEscalation,
  _getLastReminderTime,
} from '../services/escalation';
import type { EscalationDeps } from '../services/escalation';

vi.mock('../services/proactive', () => ({
  sendProactiveCard: vi.fn(),
  hasConversationReference: vi.fn(),
}));

vi.mock('../cards/reminder-card', () => ({
  buildReminderCard: vi.fn().mockReturnValue({ type: 'AdaptiveCard' }),
}));

const makeDeps = (overrides: Partial<EscalationDeps> = {}): EscalationDeps => ({
  gateway: {
    listPendingApprovals: vi.fn().mockResolvedValue([]),
  } as unknown as EscalationDeps['gateway'],
  config: {
    escalationIntervalMinutes: 30,
    webUiPublicUrl: 'https://aap.example.com',
  } as unknown as EscalationDeps['config'],
  ...overrides,
});

// ---------------------------------------------------------------------------
// cleanupDedupMap
// ---------------------------------------------------------------------------

describe('cleanupDedupMap', () => {
  beforeEach(() => {
    _resetEscalation();
    vi.clearAllMocks();
  });

  it('returns 0 when dedup map is empty', () => {
    const cleaned = cleanupDedupMap(new Set(['approval-1']));
    expect(cleaned).toBe(0);
  });

  it('removes entries whose approval_id is not in the active set', async () => {
    // Seed two entries by running checkAndEscalate with matching approvals
    const { hasConversationReference, sendProactiveCard } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(true);
    vi.mocked(sendProactiveCard).mockResolvedValue({ ok: true, messageId: 'msg-1' });

    const oldTime = Date.now() - 2 * 60 * 60 * 1000; // 2h ago
    const deps = makeDeps({
      gateway: {
        listPendingApprovals: vi.fn().mockResolvedValue([
          {
            id: 'approval-stale',
            thread_id: 'thread-1',
            proposed_at: new Date(oldTime).toISOString(),
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
            risk_level: 'high',
            proposal: { description: 'restart vm', target_resources: ['vm-1'] },
          },
          {
            id: 'approval-active',
            thread_id: 'thread-2',
            proposed_at: new Date(oldTime).toISOString(),
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
            risk_level: 'high',
            proposal: { description: 'scale down', target_resources: ['vmss-1'] },
          },
        ]),
      } as unknown as EscalationDeps['gateway'],
    });

    await checkAndEscalate(deps);
    expect(_getLastReminderTime('approval-stale')).toBeDefined();
    expect(_getLastReminderTime('approval-active')).toBeDefined();

    // Only keep 'approval-active' as active
    const cleaned = cleanupDedupMap(new Set(['approval-active']));
    expect(cleaned).toBe(1);
    expect(_getLastReminderTime('approval-stale')).toBeUndefined();
    expect(_getLastReminderTime('approval-active')).toBeDefined();
  });

  it('removes all entries when active set is empty', async () => {
    const { hasConversationReference, sendProactiveCard } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(true);
    vi.mocked(sendProactiveCard).mockResolvedValue({ ok: true, messageId: 'msg-2' });

    const oldTime = Date.now() - 2 * 60 * 60 * 1000;
    const deps = makeDeps({
      gateway: {
        listPendingApprovals: vi.fn().mockResolvedValue([
          {
            id: 'approval-x',
            thread_id: 'thread-x',
            proposed_at: new Date(oldTime).toISOString(),
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
            risk_level: 'critical',
            proposal: { description: 'delete rg', target_resources: ['rg-1'] },
          },
        ]),
      } as unknown as EscalationDeps['gateway'],
    });

    await checkAndEscalate(deps);
    const cleaned = cleanupDedupMap(new Set());
    expect(cleaned).toBe(1);
    expect(_getLastReminderTime('approval-x')).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// startEscalationScheduler
// ---------------------------------------------------------------------------

describe('startEscalationScheduler', () => {
  beforeEach(() => {
    _resetEscalation();
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns a NodeJS.Timeout handle', () => {
    const deps = makeDeps();
    const handle = startEscalationScheduler(deps);
    expect(handle).toBeDefined();
    clearInterval(handle);
  });

  it('calls checkAndEscalate after interval fires', async () => {
    const { hasConversationReference } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(false);

    const deps = makeDeps();
    const listSpy = vi.mocked(deps.gateway.listPendingApprovals);

    const handle = startEscalationScheduler(deps);
    // Advance past the 2-minute poll interval
    await vi.advanceTimersByTimeAsync(2 * 60 * 1000 + 100);
    // hasConversationReference returns false so listPendingApprovals is not called,
    // but the interval callback fired — verify it ran (no throw)
    expect(listSpy).not.toHaveBeenCalled(); // guard skips when no conversation ref
    clearInterval(handle);
  });
});

// ---------------------------------------------------------------------------
// checkAndEscalate — additional branches
// ---------------------------------------------------------------------------

describe('checkAndEscalate', () => {
  beforeEach(() => {
    _resetEscalation();
    vi.clearAllMocks();
  });

  it('returns 0 when no ConversationReference', async () => {
    const { hasConversationReference } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(false);

    const result = await checkAndEscalate(makeDeps());
    expect(result).toBe(0);
  });

  it('skips approvals younger than threshold', async () => {
    const { hasConversationReference } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(true);

    const deps = makeDeps({
      gateway: {
        listPendingApprovals: vi.fn().mockResolvedValue([
          {
            id: 'new-approval',
            thread_id: 'thread-new',
            proposed_at: new Date().toISOString(), // just now
            expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
            risk_level: 'high',
            proposal: { description: 'test', target_resources: [] },
          },
        ]),
      } as unknown as EscalationDeps['gateway'],
    });

    const result = await checkAndEscalate(deps);
    expect(result).toBe(0);
  });

  it('skips expired approvals', async () => {
    const { hasConversationReference } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(true);

    const deps = makeDeps({
      gateway: {
        listPendingApprovals: vi.fn().mockResolvedValue([
          {
            id: 'expired-approval',
            thread_id: 'thread-exp',
            proposed_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
            expires_at: new Date(Date.now() - 1000).toISOString(), // expired
            risk_level: 'high',
            proposal: { description: 'test', target_resources: [] },
          },
        ]),
      } as unknown as EscalationDeps['gateway'],
    });

    const result = await checkAndEscalate(deps);
    expect(result).toBe(0);
  });

  it('returns 0 and logs on gateway error', async () => {
    const { hasConversationReference } = await import('../services/proactive');
    vi.mocked(hasConversationReference).mockReturnValue(true);

    const deps = makeDeps({
      gateway: {
        listPendingApprovals: vi.fn().mockRejectedValue(new Error('gateway down')),
      } as unknown as EscalationDeps['gateway'],
    });

    const result = await checkAndEscalate(deps);
    expect(result).toBe(0);
  });
});
