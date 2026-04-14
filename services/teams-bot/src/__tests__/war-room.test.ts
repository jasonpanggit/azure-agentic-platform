import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  registerWarRoomThread,
  lookupWarRoomThread,
  _resetRegistry,
  syncTeamsMessageToWarRoom,
} from '../services/war-room';
import { buildWarRoomCreatedCard, buildWarRoomAnnotationCard } from '../cards/war-room-card';
import type { WarRoomCreatedPayload, WarRoomAnnotationPayload } from '../types';

// ---------------------------------------------------------------------------
// Shared test fixtures
// ---------------------------------------------------------------------------

const baseCreatedPayload: WarRoomCreatedPayload = {
  incident_id: 'inc-001',
  incident_title: 'CPU spike on vm-prod-001',
  severity: 'Sev0',
  resource_name: 'vm-prod-001',
  participants: [
    { operator_id: 'op-1', display_name: 'Alice', role: 'lead' },
    { operator_id: 'op-2', display_name: 'Bob', role: 'responder' },
  ],
  incident_url: 'https://aap.example.com/incidents/inc-001',
};

const baseAnnotationPayload: WarRoomAnnotationPayload = {
  incident_id: 'inc-001',
  incident_title: 'CPU spike on vm-prod-001',
  annotation: {
    id: 'ann-001',
    operator_id: 'op-1',
    display_name: 'Alice',
    content: 'Rebooted the service. Monitoring recovery.',
    created_at: '2026-04-15T10:30:00Z',
    trace_event_id: null,
  },
};

// ---------------------------------------------------------------------------
// WarRoomThreadRegistry
// ---------------------------------------------------------------------------

describe('WarRoomThreadRegistry', () => {
  beforeEach(() => {
    _resetRegistry();
    vi.clearAllMocks();
  });

  it('registers and looks up a thread', () => {
    registerWarRoomThread('msg-001', 'inc-001');
    expect(lookupWarRoomThread('msg-001')).toBe('inc-001');
  });

  it('returns undefined for unknown message id', () => {
    expect(lookupWarRoomThread('unknown-msg')).toBeUndefined();
  });

  it('overwrites existing registration for same message id', () => {
    registerWarRoomThread('msg-001', 'inc-001');
    registerWarRoomThread('msg-001', 'inc-002');
    expect(lookupWarRoomThread('msg-001')).toBe('inc-002');
  });

  it('_resetRegistry clears all entries', () => {
    registerWarRoomThread('msg-001', 'inc-001');
    registerWarRoomThread('msg-002', 'inc-002');
    _resetRegistry();
    expect(lookupWarRoomThread('msg-001')).toBeUndefined();
    expect(lookupWarRoomThread('msg-002')).toBeUndefined();
  });

  it('registers multiple threads independently', () => {
    registerWarRoomThread('msg-001', 'inc-001');
    registerWarRoomThread('msg-002', 'inc-002');
    registerWarRoomThread('msg-003', 'inc-003');
    expect(lookupWarRoomThread('msg-001')).toBe('inc-001');
    expect(lookupWarRoomThread('msg-002')).toBe('inc-002');
    expect(lookupWarRoomThread('msg-003')).toBe('inc-003');
  });
});

// ---------------------------------------------------------------------------
// buildWarRoomCreatedCard
// ---------------------------------------------------------------------------

describe('buildWarRoomCreatedCard', () => {
  beforeEach(() => {
    _resetRegistry();
    vi.clearAllMocks();
  });

  it('returns valid Adaptive Card schema', () => {
    const card = buildWarRoomCreatedCard(baseCreatedPayload);
    expect(card.type).toBe('AdaptiveCard');
    expect(card.version).toBe('1.5');
    expect(card.$schema as string).toContain('adaptivecards.io');
  });

  it('includes incident_id in fact set', () => {
    const card = buildWarRoomCreatedCard(baseCreatedPayload);
    expect(JSON.stringify(card)).toContain(baseCreatedPayload.incident_id);
  });

  it('includes participant names in fact set', () => {
    const card = buildWarRoomCreatedCard(baseCreatedPayload);
    const json = JSON.stringify(card);
    expect(json).toContain('Alice');
    expect(json).toContain('Bob');
  });

  it('includes Open War Room action with war_room=1', () => {
    const card = buildWarRoomCreatedCard(baseCreatedPayload);
    expect(JSON.stringify(card)).toContain('war_room=1');
  });

  it('includes Open Incident action when incident_url provided', () => {
    const card = buildWarRoomCreatedCard(baseCreatedPayload);
    expect(JSON.stringify(card)).toContain('https://aap.example.com/incidents/inc-001');
  });

  it('handles missing optional fields gracefully', () => {
    const minimalPayload: WarRoomCreatedPayload = {
      incident_id: 'inc-min',
      severity: 'Sev1',
      participants: [],
    };
    expect(() => buildWarRoomCreatedCard(minimalPayload)).not.toThrow();
    const card = buildWarRoomCreatedCard(minimalPayload);
    expect(card.type).toBe('AdaptiveCard');
  });
});

// ---------------------------------------------------------------------------
// buildWarRoomAnnotationCard
// ---------------------------------------------------------------------------

describe('buildWarRoomAnnotationCard', () => {
  beforeEach(() => {
    _resetRegistry();
    vi.clearAllMocks();
  });

  it('returns valid Adaptive Card schema', () => {
    const card = buildWarRoomAnnotationCard(baseAnnotationPayload);
    expect(card.type).toBe('AdaptiveCard');
    expect(card.version).toBe('1.5');
  });

  it('includes annotation content', () => {
    const card = buildWarRoomAnnotationCard(baseAnnotationPayload);
    expect(JSON.stringify(card)).toContain('Rebooted the service. Monitoring recovery.');
  });

  it('includes author display_name', () => {
    const card = buildWarRoomAnnotationCard(baseAnnotationPayload);
    expect(JSON.stringify(card)).toContain('Alice');
  });

  it('includes trace_event_id when set', () => {
    const payload: WarRoomAnnotationPayload = {
      ...baseAnnotationPayload,
      annotation: { ...baseAnnotationPayload.annotation, trace_event_id: 'trace-abc' },
    };
    const card = buildWarRoomAnnotationCard(payload);
    expect(JSON.stringify(card)).toContain('trace-abc');
  });

  it('omits trace_event_id block when null', () => {
    const card = buildWarRoomAnnotationCard(baseAnnotationPayload); // trace_event_id: null
    expect(JSON.stringify(card)).not.toContain('Pinned to trace event');
  });
});

// ---------------------------------------------------------------------------
// syncTeamsMessageToWarRoom
// ---------------------------------------------------------------------------

describe('syncTeamsMessageToWarRoom', () => {
  beforeEach(() => {
    _resetRegistry();
    vi.clearAllMocks();
    // Reset the env var before each test
    delete process.env.GATEWAY_INTERNAL_URL;
  });

  it('returns ok:false when GATEWAY_INTERNAL_URL not set', async () => {
    // GATEWAY_INTERNAL_URL is not set (deleted in beforeEach)
    // The module reads it at import time via ?? '' so we need to re-test
    // by checking the empty string branch — stub fetch to verify it's not called
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    // The module captures GATEWAY_INTERNAL_URL at load time as ''.
    // Since the module is already loaded, the empty-string path is already compiled in.
    // We test by importing the function directly (GATEWAY_INTERNAL_URL = '' → early return).
    const result = await syncTeamsMessageToWarRoom('inc-001', 'op-1', 'Alice', 'hello');
    expect(result.ok).toBe(false);
    expect(result.error).toContain('GATEWAY_INTERNAL_URL');
    expect(fetchSpy).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it('returns ok:true on successful gateway POST', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ annotation: { id: 'ann-001' } }),
    }));

    // Temporarily set env to non-empty by patching the module's internal usage
    // Since the const is captured at module load, we monkey-patch via a workaround:
    // use Object.defineProperty on process.env and re-import... Instead, verify via
    // a gateway URL already set in the module (defaults to '') — this test proves
    // the happy path when URL is configured by testing the function with a real env.
    // We'll inject by setting process.env and re-evaluating in an isolated import.
    // Simpler: test the branch by stubbing fetch AND verifying annotationId extracted.

    // For the happy path, we set GATEWAY_INTERNAL_URL via process.env then use
    // a dynamic import to get a fresh module instance.
    process.env.GATEWAY_INTERNAL_URL = 'http://gateway.internal';

    const { syncTeamsMessageToWarRoom: syncFresh } = await import('../services/war-room?fresh=1' as string).catch(
      () => import('../services/war-room')
    );

    const result = await syncFresh('inc-001', 'op-1', 'Alice', 'hello');
    expect(result.ok).toBe(true);
    expect(result.annotationId).toBe('ann-001');

    vi.unstubAllGlobals();
  });

  it('truncates content to 4096 chars', async () => {
    process.env.GATEWAY_INTERNAL_URL = 'http://gateway.internal';

    let capturedBody: Record<string, unknown> = {};
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, opts: RequestInit) => {
      capturedBody = JSON.parse(opts.body as string) as Record<string, unknown>;
      return Promise.resolve({
        ok: true,
        json: async () => ({ annotation: { id: 'ann-trunc' } }),
      });
    }));

    const longContent = 'x'.repeat(5000);
    const { syncTeamsMessageToWarRoom: syncFresh } = await import('../services/war-room?fresh=2' as string).catch(
      () => import('../services/war-room')
    );

    await syncFresh('inc-001', 'op-1', 'Alice', longContent);
    expect((capturedBody.content as string).length).toBe(4096);

    vi.unstubAllGlobals();
  });

  it('returns ok:false on gateway error status', async () => {
    process.env.GATEWAY_INTERNAL_URL = 'http://gateway.internal';

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: 'unavailable' }),
    }));

    const { syncTeamsMessageToWarRoom: syncFresh } = await import('../services/war-room?fresh=3' as string).catch(
      () => import('../services/war-room')
    );

    const result = await syncFresh('inc-001', 'op-1', 'Alice', 'hello');
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/unavailable|503/);

    vi.unstubAllGlobals();
  });

  it('returns ok:false on network error', async () => {
    process.env.GATEWAY_INTERNAL_URL = 'http://gateway.internal';

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

    const { syncTeamsMessageToWarRoom: syncFresh } = await import('../services/war-room?fresh=4' as string).catch(
      () => import('../services/war-room')
    );

    const result = await syncFresh('inc-001', 'op-1', 'Alice', 'hello');
    expect(result.ok).toBe(false);
    expect(result.error).toContain('ECONNREFUSED');

    vi.unstubAllGlobals();
  });

  it('uses correct endpoint path', async () => {
    process.env.GATEWAY_INTERNAL_URL = 'http://gateway.internal';

    let capturedUrl = '';
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      capturedUrl = url;
      return Promise.resolve({
        ok: true,
        json: async () => ({ annotation: { id: 'ann-url' } }),
      });
    }));

    const { syncTeamsMessageToWarRoom: syncFresh } = await import('../services/war-room?fresh=5' as string).catch(
      () => import('../services/war-room')
    );

    await syncFresh('inc-123', 'op-1', 'Alice', 'test message');
    expect(capturedUrl).toContain('/api/v1/incidents/inc-123/war-room/annotations');

    vi.unstubAllGlobals();
  });
});
