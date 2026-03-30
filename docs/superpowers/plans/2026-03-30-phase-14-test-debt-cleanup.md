# Phase 14: Test Debt Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore CI signal by implementing tests that matter and cleanly marking those that genuinely require live infrastructure.

**Architecture:** Four tasks targeting three different services (Python API gateway, Next.js web UI, Teams bot TypeScript). Critical discovery: the SSE heartbeat is implemented in `services/web-ui/app/api/stream/route.ts` (Next.js TypeScript), NOT in the Python gateway — the stub file `services/api-gateway/tests/test_sse_heartbeat.py` is in the wrong service and must be replaced with a Jest test in the web UI service.

**Tech Stack:** pytest (Python), Jest + `@jest/globals` (web-ui), Vitest (teams-bot), `supertest` (teams-bot integration)

---

## File Structure

### New files
- `services/web-ui/__tests__/stream.test.ts` — Jest tests for SSE heartbeat (replacing Python stubs)
- `services/web-ui/__tests__/ChatPanel.test.tsx` — meaningful web UI component tests
- `services/web-ui/__tests__/useAuth.test.tsx` — meaningful auth hook tests

### Modified files
- `services/api-gateway/tests/test_sse_heartbeat.py` — replace stubs with explicit skip pointing to correct service
- `services/web-ui/__tests__/layout.test.tsx` — delete (replaced by ChatPanel.test.tsx)
- `services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts` — remove outer `describe.skip`, add active tests
- `services/detection-plane/tests/integration/test_pipeline_flow.py` — implement with mocks
- `services/detection-plane/tests/integration/test_round_trip.py` — implement with mocks
- `services/detection-plane/tests/integration/test_dedup_load.py` — explicit skip with reason
- `services/detection-plane/tests/integration/test_activity_log.py` — explicit skip with reason
- `services/detection-plane/tests/integration/test_state_sync.py` — explicit skip with reason

---

## Chunk 1: SSE Heartbeat Tests (Task 14-01)

### Task 14-01: Implement SSE Heartbeat Tests in the Correct Service

**Files:**
- Modify: `services/api-gateway/tests/test_sse_heartbeat.py` — replace Python stubs with explicit skip
- Create: `services/web-ui/__tests__/stream.test.ts` — Jest tests for actual SSE heartbeat

**Context:** The SSE heartbeat lives in `services/web-ui/app/api/stream/route.ts` (TypeScript). It uses `setInterval` with `HEARTBEAT_INTERVAL_MS = 20_000`. The Python stub file `test_sse_heartbeat.py` is in the wrong service — it was written before the implementation moved to the web UI. We replace it with a clear redirect comment and add actual Jest tests in the web UI.

**Key implementation detail from `stream/route.ts`:**
- Heartbeat is `setInterval(() => { controller.enqueue(': heartbeat\n\n') }, 20_000)`
- Heartbeat only fires when `!aborted`
- The SSE route tests must use Jest's fake timers (`jest.useFakeTimers()`) to avoid 20-second real waits

- [ ] **Step 1: Read the full SSE route implementation**

```bash
cat services/web-ui/app/api/stream/route.ts
```

Confirm:
- `HEARTBEAT_INTERVAL_MS = 20_000` (line 7)
- `setInterval(() => { controller.enqueue(': heartbeat\n\n') }, HEARTBEAT_INTERVAL_MS)` (line ~85-93)
- Route is `GET /api/stream?thread_id=...&type=token`

- [ ] **Step 2: Update Python stub file to redirect to correct location**

Replace `services/api-gateway/tests/test_sse_heartbeat.py` with:

```python
"""SSE heartbeat tests — moved to web UI service.

The SSE heartbeat (UI-008) is implemented in the Next.js web UI at:
  services/web-ui/app/api/stream/route.ts

Tests for the heartbeat are in:
  services/web-ui/__tests__/stream.test.ts

These Python stubs are kept as placeholders to avoid breaking pytest
collection — they are permanently skipped with an explanatory message.
"""
import pytest


class TestSSEHeartbeat:
    """SSE heartbeat tests — see services/web-ui/__tests__/stream.test.ts."""

    @pytest.mark.skip(
        reason=(
            "SSE heartbeat is implemented in services/web-ui/app/api/stream/route.ts "
            "(TypeScript/Next.js). Tests are in services/web-ui/__tests__/stream.test.ts. "
            "This Python file is kept as a tombstone to document the move."
        )
    )
    def test_heartbeat_sent_every_20_seconds(self):
        pass

    @pytest.mark.skip(
        reason=(
            "SSE heartbeat is implemented in services/web-ui/app/api/stream/route.ts. "
            "See services/web-ui/__tests__/stream.test.ts for the Jest implementation."
        )
    )
    def test_heartbeat_prevents_container_app_timeout(self):
        pass
```

- [ ] **Step 3: Run Python tests to confirm the stubs still pass with explicit skip**

```bash
python -m pytest services/api-gateway/tests/test_sse_heartbeat.py -v
```

Expected: 2 tests SKIPPED (not FAILED).

- [ ] **Step 4: Write Jest tests for SSE heartbeat in web UI**

Create `services/web-ui/__tests__/stream.test.ts`:

```typescript
/**
 * Tests for SSE stream route heartbeat behavior (UI-008).
 *
 * Tests the heartbeat emitted in services/web-ui/app/api/stream/route.ts.
 * Uses Jest fake timers to avoid 20-second real waits.
 *
 * NOTE on drain strategy: With fake timers active, `setTimeout` in the drain
 * loop is also frozen. We use a WritableStream (TransformStream) to capture
 * bytes synchronously rather than relying on Promise.race with setTimeout.
 */
import { describe, it, expect, jest, beforeEach, afterEach } from '@jest/globals';

describe('SSE stream route: heartbeat (UI-008)', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.resetModules();
    global.fetch = jest.fn() as any;
    // Mock fetch to return a pending run — keeps the polling loop alive
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ thread_id: 'th_123', run_status: 'in_progress', reply: null }),
    } as Response);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('emits ": heartbeat" SSE comment after 20-second interval fires', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'http://localhost:3000';

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_123&type=token');
    const req = new Request(url.toString());
    const response = await GET(req as any);

    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/event-stream');
    expect(response.body).not.toBeNull();

    // Collect bytes that have been enqueued synchronously into the stream
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();

    // Advance fake time by 21 seconds — this triggers the setInterval callback
    // which enqueues the heartbeat into the ReadableStream synchronously
    await jest.advanceTimersByTimeAsync(21_000);

    // Now read without a timeout-based race — the chunk is already in the buffer
    // ReadableStream.read() resolves immediately if data is enqueued
    const firstRead = await reader.read();
    const output = firstRead.value ? decoder.decode(firstRead.value) : '';

    expect(output).toContain(': heartbeat');
    await reader.cancel();
  });

  it('response has correct SSE Content-Type header', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'http://localhost:3000';

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_abc&type=token');
    const req = new Request(url.toString());
    const response = await GET(req as any);

    expect(response.headers.get('Content-Type')).toBe('text/event-stream');
    expect(response.headers.get('Cache-Control')).toContain('no-cache');
    await response.body!.cancel();
  });

  it('returns 400 when thread_id is missing', async () => {
    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?type=token');
    const req = new Request(url.toString());
    const response = await GET(req as any);

    expect(response.status).toBe(400);
  });
});
```

- [ ] **Step 5: Run Jest tests**

```bash
cd services/web-ui
npm test -- --testPathPattern="stream.test"
```

Expected: Both heartbeat tests PASS.

- [ ] **Step 6: Commit**

```bash
git add services/api-gateway/tests/test_sse_heartbeat.py \
        services/web-ui/__tests__/stream.test.ts
git commit -m "test: move SSE heartbeat tests from Python stub to Jest in web-ui; add explicit skip tombstone in gateway (CONCERNS 3.3)"
```

---

## Chunk 2: Web UI Placeholder Tests (Task 14-02)

### Task 14-02: Replace Web UI Empty Placeholder Tests

**Files:**
- Delete: `services/web-ui/__tests__/layout.test.tsx`
- Delete: `services/web-ui/__tests__/auth.test.tsx` (if it exists with empty stubs)
- Create: `services/web-ui/__tests__/ChatPanel.test.tsx`
- Create: `services/web-ui/__tests__/useAuth.test.tsx`

**Context:** `layout.test.tsx` has 7 `it.skip` with `// TODO: Plan 05-01` bodies. These provide no CI signal. We delete them and add tests for actual components: `ChatPanel` and `useAuth` hook. Framework: `@jest/globals` (confirmed from imports in `layout.test.tsx`).

**Note:** Before writing component tests, read the actual `ChatPanel` component and `useAuth` hook to understand their interfaces.

- [ ] **Step 1: Locate `ChatPanel` and `useAuth` in the codebase**

```bash
find services/web-ui -name "ChatPanel*" -o -name "useAuth*" | head -20
```

Read the component/hook files to understand props and return values:

```bash
cat services/web-ui/app/components/ChatPanel.tsx 2>/dev/null || \
  cat services/web-ui/components/ChatPanel.tsx 2>/dev/null || \
  echo "ChatPanel not found — check component structure"

cat services/web-ui/app/hooks/useAuth.ts 2>/dev/null || \
  cat services/web-ui/hooks/useAuth.ts 2>/dev/null || \
  echo "useAuth not found — check hook structure"
```

**If components are found:** Use their actual prop interfaces in the tests below.
**If components are not found:** Create minimal mock-based tests that test the behavior described in the spec (ChatPanel renders messages, useAuth returns dev user in dev mode).

- [ ] **Step 2: Delete the empty stub files**

```bash
rm services/web-ui/__tests__/layout.test.tsx
# Check if auth.test.tsx exists and has only empty stubs
ls services/web-ui/__tests__/auth.test.tsx 2>/dev/null && \
  grep -c "TODO" services/web-ui/__tests__/auth.test.tsx && \
  rm services/web-ui/__tests__/auth.test.tsx || echo "auth.test.tsx does not exist"
```

- [ ] **Step 3: Write `ChatPanel.test.tsx`**

After reading the actual `ChatPanel` component in Step 1, write tests that match its real interface. The following is a template — adapt the import path and prop names to match the actual component:

```typescript
/**
 * Tests for ChatPanel component — replaces empty Plan 05-01 stubs.
 * Adjust import path to match actual ChatPanel location.
 */
import { describe, it, expect, jest } from '@jest/globals';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

// TODO after Step 1: update this import path to the actual component location
// import { ChatPanel } from '../app/components/ChatPanel';
// OR: import ChatPanel from '../components/ChatPanel';

// If ChatPanel doesn't exist yet, create a minimal stub in the component location first.

describe('ChatPanel', () => {
  const mockMessages = [
    { id: '1', role: 'user' as const, content: 'Hello' },
    { id: '2', role: 'assistant' as const, content: 'Hi there' },
  ];

  it('renders all provided messages', () => {
    const onSend = jest.fn() as jest.Mock<(msg: string) => void>;
    // Adjust component import and props to match actual interface
    // render(<ChatPanel messages={mockMessages} onSend={onSend} />);
    // expect(screen.getByText('Hello')).toBeInTheDocument();
    // expect(screen.getByText('Hi there')).toBeInTheDocument();
    //
    // NOTE: Implement after reading actual ChatPanel in Step 1.
    // If ChatPanel accepts different props, update accordingly.
    expect(true).toBe(true); // placeholder — replace with real assertions
  });

  it('calls onSend with message text when Enter is pressed', () => {
    const onSend = jest.fn() as jest.Mock<(msg: string) => void>;
    // render(<ChatPanel messages={[]} onSend={onSend} />);
    // const input = screen.getByRole('textbox');
    // fireEvent.change(input, { target: { value: 'test message' } });
    // fireEvent.keyDown(input, { key: 'Enter' });
    // expect(onSend).toHaveBeenCalledWith('test message');
    expect(true).toBe(true); // placeholder — replace with real assertions
  });

  it('does not call onSend when input is empty', () => {
    const onSend = jest.fn() as jest.Mock<(msg: string) => void>;
    // render(<ChatPanel messages={[]} onSend={onSend} />);
    // const input = screen.getByRole('textbox');
    // fireEvent.keyDown(input, { key: 'Enter' });
    // expect(onSend).not.toHaveBeenCalled();
    expect(true).toBe(true); // placeholder — replace with real assertions
  });
});
```

**IMPORTANT:** Replace the placeholder `expect(true).toBe(true)` lines with real assertions based on the actual `ChatPanel` component found in Step 1. The test file must have working assertions — do not commit with placeholder assertions.

- [ ] **Step 4: Write `useAuth.test.tsx`**

After reading the actual `useAuth` hook in Step 1:

```typescript
/**
 * Tests for useAuth hook — replaces empty Plan 05-01 stubs.
 * Adjust import path to match actual hook location.
 */
import { describe, it, expect } from '@jest/globals';
import { renderHook } from '@testing-library/react';

// TODO after Step 1: update import path
// import { useAuth } from '../app/hooks/useAuth';
// OR: import { useAuth } from '../hooks/useAuth';

describe('useAuth hook', () => {
  it('returns a dev user object when NEXT_PUBLIC_DEV_MODE is true', () => {
    process.env.NEXT_PUBLIC_DEV_MODE = 'true';
    // const { result } = renderHook(() => useAuth());
    // expect(result.current).not.toBeNull();
    // expect(result.current?.name).toBeDefined();
    expect(true).toBe(true); // placeholder — replace with real assertions
  });

  it('returns null when NEXT_PUBLIC_DEV_MODE is false and no MSAL account', () => {
    process.env.NEXT_PUBLIC_DEV_MODE = 'false';
    // Mock MSAL to return no accounts
    // const { result } = renderHook(() => useAuth());
    // expect(result.current).toBeNull();
    expect(true).toBe(true); // placeholder — replace with real assertions
  });
});
```

**IMPORTANT:** Replace placeholders with real assertions after reading the actual hook.

- [ ] **Step 5: Verify no placeholder assertions remain before running tests**

```bash
# This MUST return zero matches before you proceed.
# If it finds any, go back and replace the placeholders with real assertions.
grep -rn "expect(true).toBe(true)" services/web-ui/__tests__/ChatPanel.test.tsx \
                                   services/web-ui/__tests__/useAuth.test.tsx
```

Expected: **Zero matches.** If any placeholder remains, the test technically passes but provides zero coverage — which violates the spec's requirement for "meaningful coverage." Fix all placeholders before continuing.

- [ ] **Step 6: Run the web UI test suite**

```bash
cd services/web-ui
npm test
```

Expected: No TODO/empty tests. `ChatPanel.test.tsx` and `useAuth.test.tsx` run and pass with real assertions. `layout.test.tsx` is gone.

- [ ] **Step 7: Commit**

```bash
git add services/web-ui/__tests__/ChatPanel.test.tsx \
        services/web-ui/__tests__/useAuth.test.tsx
git rm services/web-ui/__tests__/layout.test.tsx
# Remove auth.test.tsx only if it was deleted in Step 2
# git rm services/web-ui/__tests__/auth.test.tsx
git commit -m "test(web-ui): replace empty Plan 05-01 stubs with meaningful ChatPanel and useAuth tests (CONCERNS 3.4)"
```

---

## Chunk 3: Teams Bot CI Signal (Task 14-03)

### Task 14-03: Restore Teams Bot CI Signal

**Files:**
- Modify: `services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts`

**Context:** The test file uses `describe.skip(...)` which skips all 6 tests. Framework is **Vitest** (confirmed from `import { describe, it } from "vitest"` at line 1) — NOT Jest. The Teams bot uses `express` with `CloudAdapter`. The `/health` endpoint is registered via `healthRouter`. The `/api/messages` endpoint is registered at line 53 via `adapter.process()`.

**Key insight:** `POST /api/messages` with a valid Bot Framework `Activity` payload requires real auth — it will return 401 with an empty/invalid body. But 401 proves the route exists. A bare `fetch` with `{}` body will likely return 401 or 400 — both are acceptable (neither 404 nor 500).

**Note:** The `supertest` package must be available as a dev dependency for the integration tests. Check first:

```bash
cat services/teams-bot/package.json | grep supertest
```

If not present, add it: `npm install --save-dev supertest @types/supertest`

- [ ] **Step 1: Read the teams-bot index.ts to understand app structure**

```bash
cat services/teams-bot/src/index.ts
```

Confirm:
- Express app exported or accessible for testing
- `/api/messages` route exists
- Health router path (likely `/health`)

- [ ] **Step 2: Read the existing test file structure**

```bash
cat services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts
```

Note the `import { describe, it } from "vitest"` — Vitest framework. We need `vi`, `expect`, etc. from vitest.

- [ ] **Step 3: Check if `supertest` is available**

```bash
cd services/teams-bot
cat package.json | grep -E "supertest|vitest"
```

If `supertest` is not present:

```bash
npm install --save-dev supertest @types/supertest
```

- [ ] **Step 4: Ensure `app` is exported from `index.ts`**

```bash
grep -n "export" services/teams-bot/src/index.ts
```

**If `app` is NOT exported:** Add `export { app };` on the line immediately before `app.listen(...)`:

```typescript
// In index.ts — add this line before app.listen()
export { app };

app.listen(config.port, () => {
  console.log(`Teams bot listening on port ${config.port}`);
```

Then verify the export was added:

```bash
grep -n "export.*app" services/teams-bot/src/index.ts
```

Expected: Shows `export { app }` before the `listen` call.

**STOP: Do not proceed to Step 5 until Step 4 confirms `app` is exported.**

- [ ] **Step 5: Write the active integration tests**

Replace `teams-e2e-stubs.test.ts` content with:

```typescript
import { describe, it, expect, vi } from "vitest";
import request from "supertest";

/**
 * Teams bot integration tests.
 *
 * These tests verify the bot Express server is wired correctly — health
 * endpoint returns 200, and /api/messages route exists (returns 400/401).
 *
 * Full Teams round-trip tests (requiring live Teams environment + bot
 * registration) are kept as inner it.skip with explicit reason strings.
 */

// Import the Express app (not the listen call)
// Note: index.ts must export { app } for this to work.
// If it doesn't, refactor index.ts to export app before listen().
import { app } from "../../index";

describe("Teams bot integration tests", () => {

  describe("Active tests — run in CI without live environment", () => {

    it("GET /health returns 200 (liveness probe)", async () => {
      const response = await request(app).get("/health");
      expect(response.status).toBe(200);
      expect(response.body).toMatchObject({ status: expect.stringMatching(/ok|healthy/) });
    });

    it("POST /api/messages with empty body returns 400 or 401, not 404 or 500", async () => {
      const response = await request(app)
        .post("/api/messages")
        .send({})
        .set("Content-Type", "application/json");
      // 401 = endpoint exists, auth required
      // 400 = endpoint exists, bad request
      // 404 = route not found (FAIL)
      // 500 = unhandled error (FAIL)
      expect([400, 401]).toContain(response.status);
    });

  });

  describe("Phase 6 integration tests (require live Teams environment)", () => {

    it.skip("SC-1: Natural-language message routed to Orchestrator returns triage summary within 30s", async () => {
      // Requires: registered Teams bot, live Foundry endpoint, real auth token
      // Send "investigate the CPU alert on vm-prod-01" to the bot
      // Assert: response is a structured triage summary within 30 seconds
    });

    it.skip("SC-2: Alert fires -> Adaptive Card posted to channel within 10s of Cosmos record creation", async () => {
      // Requires: Teams channel, Cosmos DB with live data, bot registration
    });

    it.skip("SC-3: Approval card posted -> operator clicks Reject -> Cosmos updated -> card updated in-place", async () => {
      // Requires: Teams channel, high-risk remediation proposal, live approval flow
    });

    it.skip("SC-4: Web UI and Teams share same thread_id for an incident", async () => {
      // Requires: live Web UI + Teams bot running against same Foundry instance
    });

    it.skip("SC-5: Unacted approval triggers escalation reminder after configured interval", async () => {
      // Requires: pending approval in Cosmos, running escalation scheduler, Teams channel
    });

    it.skip("SC-6: Approved remediation executes -> outcome card posted within 60s", async () => {
      // Requires: synthetic low-risk remediation, full Foundry agent pipeline
    });

  });

});
```

- [ ] **Step 6: Run the Teams bot tests**

```bash
cd services/teams-bot
npm test
```

Expected:
- `GET /health returns 200` → PASS
- `POST /api/messages...` → PASS (status 400 or 401)
- 6 inner `it.skip` → SKIPPED
- No tests should FAIL

- [ ] **Step 7: Commit**

```bash
git add services/teams-bot/src/__tests__/integration/teams-e2e-stubs.test.ts \
        services/teams-bot/src/index.ts \
        services/teams-bot/package.json \
        services/teams-bot/package-lock.json
git commit -m "test(teams-bot): restore CI signal with health and messages endpoint tests; mark live-env tests with explicit skip reason (CONCERNS 3.2)"
```

---

## Chunk 4: Detection Plane Test Hygiene (Task 14-04)

### Task 14-04: Replace Bare `pass` Bodies in Detection Plane Integration Tests

**Files:**
- Modify: `services/detection-plane/tests/integration/test_pipeline_flow.py`
- Modify: `services/detection-plane/tests/integration/test_round_trip.py`
- Modify: `services/detection-plane/tests/integration/test_dedup_load.py`
- Modify: `services/detection-plane/tests/integration/test_activity_log.py`
- Modify: `services/detection-plane/tests/integration/test_state_sync.py`

**Context:** All 5 files have bare `pass` with `# TODO` comments — no CI signal at all. Modules `classify_domain.py` and `payload_mapper.py` are confirmed import-safe (pure Python, no Azure SDK at module level). We implement `test_pipeline_flow.py` and `test_round_trip.py` with mocks; the other 3 get explicit `pytest.skip` with infrastructure conditions.

- [ ] **Step 1: Read the detection plane modules to understand their interfaces**

```bash
cat services/detection-plane/classify_domain.py
cat services/detection-plane/payload_mapper.py
```

Note:
- `classify_domain.py` has `DOMAIN_MAPPINGS` dict and `classify_domain(resource_type: str) -> str`
- `payload_mapper.py` has `map_detection_result_to_incident_payload(detection_result: dict) -> dict`

- [ ] **Step 2: Read the existing test files to see current structure**

```bash
for f in services/detection-plane/tests/integration/test_*.py; do
  echo "=== $f ==="; cat "$f"; echo
done
```

- [ ] **Step 3: Implement `test_pipeline_flow.py`**

```python
# services/detection-plane/tests/integration/test_pipeline_flow.py
"""Detection plane pipeline flow integration tests (CONCERNS 3.1).

Tests classify_domain() with known alert payloads and verifies event schema.
Import-safe: classify_domain.py has no Azure SDK at module level.
"""
import pytest


class TestPipelineFlow:
    """Tests for the detect → classify → map pipeline."""

    def test_classify_domain_compute_resource(self):
        """classify_domain maps compute resource types to 'compute' domain."""
        from services.detection_plane.classify_domain import classify_domain

        result = classify_domain("Microsoft.Compute/virtualMachines")
        assert result == "compute"

    def test_classify_domain_network_resource(self):
        """classify_domain maps network resource types to 'network' domain."""
        from services.detection_plane.classify_domain import classify_domain

        result = classify_domain("Microsoft.Network/virtualNetworks")
        assert result == "network"

    def test_classify_domain_arc_resource(self):
        """classify_domain maps Arc resource types to 'arc' domain."""
        from services.detection_plane.classify_domain import classify_domain

        result = classify_domain("Microsoft.HybridCompute/machines")
        assert result == "arc"

    def test_classify_domain_unknown_returns_default(self):
        """classify_domain returns a non-empty string for unknown resource types."""
        from services.detection_plane.classify_domain import classify_domain

        result = classify_domain("Microsoft.Unknown/resources")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_classify_domain_empty_string_does_not_raise(self):
        """classify_domain handles empty string input gracefully."""
        from services.detection_plane.classify_domain import classify_domain

        result = classify_domain("")
        assert isinstance(result, str)
```

- [ ] **Step 4: Implement `test_round_trip.py`**

```python
# services/detection-plane/tests/integration/test_round_trip.py
"""Detection plane payload round-trip tests (CONCERNS 3.1).

Tests map_detection_result_to_incident_payload() with mock alert data.
Import-safe: payload_mapper.py has no Azure SDK at module level.
"""
import pytest


SAMPLE_DETECTION_RESULT = {
    "incident_id": "test-incident-001",
    "severity": "Sev2",
    "resource_type": "Microsoft.Compute/virtualMachines",
    "resource_id": "/subscriptions/sub-123/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-01",
    "subscription_id": "sub-123",
    "detection_rule": "HighCpuUtilization",
    "title": "High CPU utilization detected on vm-01",
    "description": "CPU utilization exceeded 95% for 15 minutes",
    "kql_evidence": "Perf | where ObjectName == 'Processor' | where CounterValue > 95",
    "timestamp": "2026-03-30T10:00:00Z",
}


class TestRoundTrip:
    """Tests for detection result → incident payload mapping."""

    def test_mapped_payload_has_required_fields(self):
        """map_detection_result_to_incident_payload returns all required IncidentPayload fields."""
        from services.detection_plane.payload_mapper import map_detection_result_to_incident_payload

        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)

        required_fields = [
            "incident_id",
            "severity",
            "domain",
            "detection_rule",
            "title",
            "description",
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

    def test_domain_is_populated_from_resource_type(self):
        """Mapped payload domain is derived from resource_type, not empty."""
        from services.detection_plane.payload_mapper import map_detection_result_to_incident_payload

        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert result.get("domain"), "domain field must be non-empty"
        assert isinstance(result["domain"], str)

    def test_severity_preserved_from_input(self):
        """Severity from detection result is preserved in the mapped payload."""
        from services.detection_plane.payload_mapper import map_detection_result_to_incident_payload

        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert result["severity"] == "Sev2"

    def test_incident_id_preserved_from_input(self):
        """Incident ID from detection result is preserved in the mapped payload."""
        from services.detection_plane.payload_mapper import map_detection_result_to_incident_payload

        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert result["incident_id"] == "test-incident-001"

    def test_affected_resources_populated(self):
        """Mapped payload includes affected_resources list."""
        from services.detection_plane.payload_mapper import map_detection_result_to_incident_payload

        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert "affected_resources" in result
        assert len(result["affected_resources"]) >= 1
```

- [ ] **Step 5: Add explicit skips to the 3 infrastructure-dependent files**

Replace bare `pass` in `test_dedup_load.py`:

```python
# services/detection-plane/tests/integration/test_dedup_load.py
"""Deduplication load test — requires Fabric deployment."""
import pytest


@pytest.fixture(autouse=True)
def skip_without_fabric():
    pytest.skip(
        "requires Fabric deployment — enable when enable_fabric_data_plane=true "
        "and FABRIC_EVENTHOUSE_ENDPOINT is configured"
    )


class TestDedupLoad:
    def test_dedup_rejects_duplicate_incident_within_window(self):
        pass

    def test_dedup_allows_same_incident_after_window_expires(self):
        pass
```

Replace bare `pass` in `test_activity_log.py`:

```python
# services/detection-plane/tests/integration/test_activity_log.py
"""Activity log integration test — requires Fabric Activator deployment."""
import pytest


@pytest.fixture(autouse=True)
def skip_without_fabric():
    pytest.skip(
        "requires Fabric Activator deployment — enable when enable_fabric_data_plane=true "
        "and Activator webhook is configured"
    )


class TestActivityLog:
    def test_activator_triggers_on_sev0_alert(self):
        pass

    def test_activity_log_records_agent_action(self):
        pass
```

Replace bare `pass` in `test_state_sync.py`:

```python
# services/detection-plane/tests/integration/test_state_sync.py
"""State sync integration test — requires Fabric OneLake."""
import pytest


@pytest.fixture(autouse=True)
def skip_without_fabric():
    pytest.skip(
        "requires Fabric OneLake deployment — enable when ONELAKE_ENDPOINT "
        "is configured and Fabric workspace is provisioned"
    )


class TestStateSync:
    def test_incident_state_synced_to_onelake(self):
        pass

    def test_remediation_event_persisted_to_onelake(self):
        pass
```

- [ ] **Step 6: Run detection plane tests to confirm new tests pass and others skip**

```bash
python -m pytest services/detection-plane/tests/integration/ -v
```

Expected output:
```
test_pipeline_flow.py::TestPipelineFlow::test_classify_domain_compute_resource PASSED
test_pipeline_flow.py::TestPipelineFlow::test_classify_domain_network_resource PASSED
test_pipeline_flow.py::TestPipelineFlow::test_classify_domain_arc_resource PASSED
test_pipeline_flow.py::TestPipelineFlow::test_classify_domain_unknown_returns_default PASSED
test_pipeline_flow.py::TestPipelineFlow::test_classify_domain_empty_string_does_not_raise PASSED
test_round_trip.py::TestRoundTrip::test_mapped_payload_has_required_fields PASSED
test_round_trip.py::TestRoundTrip::test_domain_is_populated_from_resource_type PASSED
test_round_trip.py::TestRoundTrip::test_severity_preserved_from_input PASSED
test_round_trip.py::TestRoundTrip::test_incident_id_preserved_from_input PASSED
test_round_trip.py::TestRoundTrip::test_affected_resources_populated PASSED
test_dedup_load.py::... SKIPPED (requires Fabric deployment...)
test_activity_log.py::... SKIPPED (requires Fabric Activator...)
test_state_sync.py::... SKIPPED (requires Fabric OneLake...)
```

If `test_pipeline_flow.py` or `test_round_trip.py` fail due to import errors (Azure SDK module-level instantiation), add:

```python
pytestmark = pytest.mark.skipif(
    not _can_import_module(),
    reason="module imports require Azure SDK initialization"
)
```

Where `_can_import_module()` tries `import services.detection_plane.classify_domain` and returns `False` on exception.

- [ ] **Step 7: Run full Python test suite**

```bash
python -m pytest services/ -v --timeout=30 -x 2>&1 | tail -30
```

Expected: All gateway and detection plane tests pass; known skips remain skipped.

- [ ] **Step 8: Commit**

```bash
git add services/detection-plane/tests/integration/test_pipeline_flow.py \
        services/detection-plane/tests/integration/test_round_trip.py \
        services/detection-plane/tests/integration/test_dedup_load.py \
        services/detection-plane/tests/integration/test_activity_log.py \
        services/detection-plane/tests/integration/test_state_sync.py
git commit -m "test(detection-plane): implement pipeline and round-trip tests; replace bare pass with explicit pytest.skip in infra-dependent tests (CONCERNS 3.1)"
```

---

## Verification Checklist

- [ ] `python -m pytest services/api-gateway/tests/test_sse_heartbeat.py -v` — 2 SKIPPED with explanatory message
- [ ] `cd services/web-ui && npm test -- --testPathPattern="stream.test"` — 2 heartbeat tests PASS
- [ ] `ls services/web-ui/__tests__/layout.test.tsx` — file does not exist (deleted)
- [ ] `cd services/web-ui && npm test` — no TODO/empty tests; ChatPanel + useAuth tests pass
- [ ] `cd services/teams-bot && npm test` — `GET /health` PASS, `POST /api/messages` PASS, 6 integration tests SKIPPED with reason
- [ ] `python -m pytest services/detection-plane/tests/integration/ -v` — 10 mock tests PASS, 3 infra tests SKIPPED with reason
- [ ] No test file has a bare `pass` body with a `# TODO` comment
- [ ] `python -m pytest services/ -v --timeout=30` — all passing tests still pass
