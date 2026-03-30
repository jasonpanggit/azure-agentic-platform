# Phase 11: Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate live security gaps — auth tokens not forwarded, rate limiter unused, hardcoded URLs, brittle internal poll configuration.

**Architecture:** Five independent tasks, executed sequentially because Tasks 11-02 and 11-03 share the same 5 proxy route files. All changes are pure Python or TypeScript — no infrastructure changes required. New `http_rate_limiter.py` module added alongside (not replacing) the existing remediation-scoped `rate_limiter.py`.

**Tech Stack:** FastAPI (Python), Next.js App Router (TypeScript), `slowapi` (or in-memory rate limiting), `pytest`, Jest (`@jest/globals`)

---

## File Structure

### New files
- `services/api-gateway/http_rate_limiter.py` — per-IP HTTP rate limiter (sliding window, in-memory)
- `services/api-gateway/tests/test_http_rate_limiter.py` — unit tests for the HTTP rate limiter

### Modified files
- `services/api-gateway/main.py` — wire rate limiter middleware
- `services/web-ui/app/api/proxy/chat/route.ts` — add auth pass-through + remove hardcoded URL
- `services/web-ui/app/api/proxy/chat/result/route.ts` — add auth pass-through + remove hardcoded URL
- `services/web-ui/app/api/proxy/incidents/route.ts` — add auth pass-through + remove hardcoded URL
- `services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts` — add auth pass-through + remove hardcoded URL
- `services/web-ui/app/api/proxy/approvals/[approvalId]/reject/route.ts` — add auth pass-through + remove hardcoded URL
- `services/web-ui/app/api/stream/route.ts` — fix hardcoded `localhost:3000` internal poll URL
- `e2e/arc-mcp-server.spec.ts` — confirm `ARC_MCP_SERVER_URL` variable name (already correct)
- `services/web-ui/.env.example` — document new env vars

---

## Chunk 1: HTTP Rate Limiter (Task 11-01)

### Task 11-01: Add HTTP Rate Limiter to API Gateway

**Files:**
- Create: `services/api-gateway/http_rate_limiter.py`
- Create: `services/api-gateway/tests/test_http_rate_limiter.py`
- Modify: `services/api-gateway/main.py`

**Context:** The existing `rate_limiter.py` is a per-agent *remediation* guard (REMEDI-006) — it takes `(agent_name, subscription_id)` and must not be modified. We need a separate in-memory per-IP HTTP rate limiter. Using `collections.defaultdict` + `time` avoids adding `slowapi` as a dependency.

- [ ] **Step 1: Write failing tests for `http_rate_limiter.py`**

```python
# services/api-gateway/tests/test_http_rate_limiter.py
"""Tests for per-IP HTTP rate limiter (CONCERNS 1.5)."""
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi import Request
from fastapi.testclient import TestClient
from fastapi import FastAPI, status
from services.api_gateway.http_rate_limiter import HttpRateLimiter, rate_limit_middleware


class TestHttpRateLimiter:
    """Tests for HttpRateLimiter sliding window logic."""

    def test_allows_requests_within_limit(self):
        limiter = HttpRateLimiter(max_per_minute=5)
        for _ in range(5):
            result = limiter.check("127.0.0.1")
            assert result is True

    def test_blocks_request_exceeding_limit(self):
        limiter = HttpRateLimiter(max_per_minute=5)
        for _ in range(5):
            limiter.check("127.0.0.1")
        assert limiter.check("127.0.0.1") is False

    def test_different_ips_tracked_independently(self):
        limiter = HttpRateLimiter(max_per_minute=2)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        assert limiter.check("1.2.3.4") is False
        # Different IP should still pass
        assert limiter.check("5.6.7.8") is True

    def test_retry_after_seconds_returned_on_block(self):
        limiter = HttpRateLimiter(max_per_minute=1)
        limiter.check("127.0.0.1")
        retry_after = limiter.retry_after("127.0.0.1")
        assert 0 < retry_after <= 60

    def test_record_appended_after_allow(self):
        limiter = HttpRateLimiter(max_per_minute=10)
        limiter.check("10.0.0.1")
        assert len(limiter._windows["10.0.0.1"]) == 1


class TestRateLimitEndpoints:
    """Integration tests — rate limiter wired on /api/v1/chat and /api/v1/incidents."""

    def _make_app_with_limiter(self, chat_limit: int, incidents_limit: int) -> FastAPI:
        """Build a minimal FastAPI app with rate limiter middleware for testing."""
        from services.api_gateway.http_rate_limiter import (
            HttpRateLimiter,
        )

        app = FastAPI()
        chat_limiter = HttpRateLimiter(max_per_minute=chat_limit)
        incidents_limiter = HttpRateLimiter(max_per_minute=incidents_limit)

        @app.post("/api/v1/chat")
        async def chat_endpoint(request: Request):
            ip = request.client.host if request.client else "unknown"
            if not chat_limiter.check(ip):
                retry = chat_limiter.retry_after(ip)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "retry_after": retry},
                    status_code=429,
                )
            return {"status": "ok"}

        @app.get("/api/v1/incidents")
        async def incidents_endpoint(request: Request):
            ip = request.client.host if request.client else "unknown"
            if not incidents_limiter.check(ip):
                retry = incidents_limiter.retry_after(ip)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "retry_after": retry},
                    status_code=429,
                )
            return {"incidents": []}

        return app

    def test_chat_returns_429_on_11th_request(self):
        app = self._make_app_with_limiter(chat_limit=10, incidents_limit=30)
        client = TestClient(app)
        for i in range(10):
            resp = client.post("/api/v1/chat", json={})
            assert resp.status_code == 200, f"Request {i+1} should be allowed"
        resp = client.post("/api/v1/chat", json={})
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"] == "Rate limit exceeded"
        assert "retry_after" in body

    def test_incidents_returns_429_on_31st_request(self):
        app = self._make_app_with_limiter(chat_limit=10, incidents_limit=30)
        client = TestClient(app)
        for i in range(30):
            resp = client.get("/api/v1/incidents")
            assert resp.status_code == 200, f"Request {i+1} should be allowed"
        resp = client.get("/api/v1/incidents")
        assert resp.status_code == 429
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_http_rate_limiter.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'services.api_gateway.http_rate_limiter'`

- [ ] **Step 3: Implement `http_rate_limiter.py`**

```python
# services/api-gateway/http_rate_limiter.py
"""Per-IP HTTP rate limiter for the API gateway (CONCERNS 1.5).

Uses a sliding window (1 minute) with in-memory storage per IP address.
This is separate from rate_limiter.py which is a per-agent remediation guard (REMEDI-006).

Limits applied in main.py:
  /api/v1/chat      — 10 req/min per IP
  /api/v1/incidents — 30 req/min per IP
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Optional

DEFAULT_CHAT_LIMIT = int(os.environ.get("HTTP_RATE_LIMIT_CHAT", "10"))
DEFAULT_INCIDENTS_LIMIT = int(os.environ.get("HTTP_RATE_LIMIT_INCIDENTS", "30"))


class HttpRateLimiter:
    """Sliding window per-IP rate limiter."""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _clean(self, ip: str) -> None:
        """Remove timestamps older than 1 minute."""
        window_start = time.monotonic() - 60.0
        self._windows[ip] = [t for t in self._windows[ip] if t > window_start]

    def check(self, ip: str) -> bool:
        """Return True if request is allowed, record it. Return False if rate limited."""
        self._clean(ip)
        if len(self._windows[ip]) >= self.max_per_minute:
            return False
        self._windows[ip].append(time.monotonic())
        return True

    def retry_after(self, ip: str) -> int:
        """Seconds until oldest request in window expires (for Retry-After header)."""
        self._clean(ip)
        if not self._windows[ip]:
            return 0
        oldest = min(self._windows[ip])
        remaining = 60.0 - (time.monotonic() - oldest)
        return max(1, int(remaining) + 1)


# Module-level instances — configured via environment variables
chat_rate_limiter = HttpRateLimiter(max_per_minute=DEFAULT_CHAT_LIMIT)
incidents_rate_limiter = HttpRateLimiter(max_per_minute=DEFAULT_INCIDENTS_LIMIT)
```

- [ ] **Step 4: Wire rate limiter in `main.py`**

In `main.py`, add the following imports and middleware after the CORS middleware registration:

```python
# Add to imports at top of main.py
from fastapi.responses import JSONResponse
from services.api_gateway.http_rate_limiter import (
    chat_rate_limiter,
    incidents_rate_limiter,
)
```

Add after the `add_correlation_id` middleware definition:

```python
@app.middleware("http")
async def apply_http_rate_limit(request: Request, call_next):
    """Apply per-IP rate limits to chat and incidents endpoints."""
    ip = request.client.host if request.client else "unknown"
    path = request.url.path

    if path == "/api/v1/chat" and request.method == "POST":
        if not chat_rate_limiter.check(ip):
            retry = chat_rate_limiter.retry_after(ip)
            return JSONResponse(
                {"detail": "Rate limit exceeded", "retry_after": retry},
                status_code=429,
            )
    elif path == "/api/v1/incidents" and request.method == "GET":
        if not incidents_rate_limiter.check(ip):
            retry = incidents_rate_limiter.retry_after(ip)
            return JSONResponse(
                {"detail": "Rate limit exceeded", "retry_after": retry},
                status_code=429,
            )

    return await call_next(request)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
python -m pytest services/api-gateway/tests/test_http_rate_limiter.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Run full gateway test suite to confirm nothing regressed**

```bash
python -m pytest services/api-gateway/tests/ -v --timeout=30
```

Expected: All existing tests pass. No remediation path tests broken.

- [ ] **Step 7: Commit**

```bash
git add services/api-gateway/http_rate_limiter.py \
        services/api-gateway/tests/test_http_rate_limiter.py \
        services/api-gateway/main.py
git commit -m "feat(api-gateway): add per-IP HTTP rate limiter for /chat and /incidents (CONCERNS 1.5)"
```

---

## Chunk 2: Auth Token Pass-Through (Task 11-02)

### Task 11-02: Web UI Proxy Routes Forward Auth Token

**Files (5 proxy routes — all modified together):**
- Modify: `services/web-ui/app/api/proxy/chat/route.ts`
- Modify: `services/web-ui/app/api/proxy/chat/result/route.ts`
- Modify: `services/web-ui/app/api/proxy/incidents/route.ts`
- Modify: `services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts`
- Modify: `services/web-ui/app/api/proxy/approvals/[approvalId]/reject/route.ts`
- Modify: `services/web-ui/.env.example`

**Context:** Server-side Next.js route handlers cannot use MSAL's browser `acquireTokenSilent`. The correct approach is pass-through: read the `Authorization` header from the incoming request (the browser already attached it via MSAL) and forward it to the gateway. The proxy never validates, refreshes, or acquires tokens — it just forwards.

- [ ] **Step 1: Read all 5 proxy route files to understand current pattern**

```bash
# Check all proxy routes exist and understand current fetch call structure
ls services/web-ui/app/api/proxy/
cat services/web-ui/app/api/proxy/chat/result/route.ts
cat services/web-ui/app/api/proxy/incidents/route.ts
cat services/web-ui/app/api/proxy/approvals/\[approvalId\]/approve/route.ts
cat services/web-ui/app/api/proxy/approvals/\[approvalId\]/reject/route.ts
```

- [ ] **Step 2: Write failing test for auth pass-through**

Create `services/web-ui/__tests__/proxy-auth.test.ts`:

```typescript
/**
 * Tests: proxy routes forward Authorization header to upstream gateway.
 * Uses jest.mock to intercept fetch calls and inspect headers.
 */
import { describe, it, expect, jest, beforeEach } from '@jest/globals';

// We test the chat proxy as representative of all 5 routes.
// The same pattern must be verified manually for the other 4.

describe('Chat proxy: Authorization header pass-through', () => {
  const MOCK_GATEWAY = 'http://gateway-test:8000';

  beforeEach(() => {
    process.env.API_GATEWAY_URL = MOCK_GATEWAY;
    process.env.NEXT_PUBLIC_DEV_MODE = 'false';
    jest.resetModules();
    global.fetch = jest.fn() as any;
  });

  it('forwards Authorization header from incoming request to upstream fetch', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ thread_id: 'th_123', run_id: 'run_456', status: 'created' }),
    } as Response);

    const { POST } = await import('../app/api/proxy/chat/route');

    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer test-access-token',
      },
      body: JSON.stringify({ message: 'hello' }),
    });

    await POST(incomingRequest as any);

    expect(global.fetch).toHaveBeenCalledWith(
      `${MOCK_GATEWAY}/api/v1/chat`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-access-token',
        }),
      })
    );
  });

  it('makes upstream call without Authorization when header is absent (dev mode)', async () => {
    process.env.NEXT_PUBLIC_DEV_MODE = 'true';
    jest.resetModules();

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ thread_id: 'th_123', run_id: 'run_456', status: 'created' }),
    } as Response);

    const { POST } = await import('../app/api/proxy/chat/route');

    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    });

    const response = await POST(incomingRequest as any);
    expect(response.status).toBe(200);
    // Fetch should have been called without Authorization header
    const fetchCall = (global.fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    const headers = fetchCall.headers as Record<string, string>;
    expect(headers['Authorization']).toBeUndefined();
  });
});
```

- [ ] **Step 3: Run test to confirm it fails**

```bash
cd services/web-ui
npm test -- --testPathPattern="proxy-auth" 2>&1 | tail -20
```

Expected: FAIL — proxy doesn't forward Authorization header yet.

- [ ] **Step 4: Update `services/web-ui/app/api/proxy/chat/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function getApiGatewayUrl(): string {
  const url = process.env.API_GATEWAY_URL;
  if (!url) {
    if (process.env.NEXT_PUBLIC_DEV_MODE === 'true') {
      return 'http://localhost:8000';
    }
    throw new Error('API_GATEWAY_URL is not configured');
  }
  return url;
}

/**
 * POST /api/proxy/chat
 *
 * Proxies chat messages from the web UI to the API gateway.
 * Forwards the Authorization header from the browser (MSAL pass-through).
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();

    const upstreamHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const authHeader = request.headers.get('Authorization');
    if (authHeader) {
      upstreamHeaders['Authorization'] = authHeader;
    }

    const res = await fetch(`${apiGatewayUrl}/api/v1/chat`, {
      method: 'POST',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
```

- [ ] **Step 5: Apply the same pattern to the other 4 proxy routes**

Apply `getApiGatewayUrl()` helper + `Authorization` header forwarding to:

- `services/web-ui/app/api/proxy/chat/result/route.ts` (GET — forwards auth on `fetch` to `${apiGatewayUrl}/api/v1/chat/${threadId}/result`)
- `services/web-ui/app/api/proxy/incidents/route.ts` (GET — forwards auth on `fetch` to `${apiGatewayUrl}/api/v1/incidents`)
- `services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts` (POST — forwards auth)
- `services/web-ui/app/api/proxy/approvals/[approvalId]/reject/route.ts` (POST — forwards auth)

The pattern for each is:
1. Add `getApiGatewayUrl()` at top of file (replacing the module-level `API_GATEWAY_URL` constant)
2. Call `getApiGatewayUrl()` inside the handler (catches `Error` → returns 502)
3. Build `upstreamHeaders` with `Content-Type` + conditional `Authorization` from `request.headers.get('Authorization')`
4. Pass `upstreamHeaders` to the upstream `fetch()` call

- [ ] **Step 6: Update `.env.example` with new env vars**

Add to `services/web-ui/.env.example`:

```
NEXT_PUBLIC_AZURE_CLIENT_ID=
NEXT_PUBLIC_TENANT_ID=
NEXT_PUBLIC_REDIRECT_URI=http://localhost:3000/callback
API_GATEWAY_URL=http://localhost:8000
# Scope for API gateway Entra ID auth — used by MSAL client-side to acquire tokens
# Example: api://<api-gateway-client-id>/access_as_user
NEXT_PUBLIC_API_GATEWAY_SCOPE=
# Site URL for SSE internal polling — set to the web UI Container App FQDN in production
# Example: https://ca-web-ui-prod.xxx.azurecontainerapps.io
NEXT_PUBLIC_SITE_URL=
```

- [ ] **Step 7: Run proxy-auth test to confirm it passes**

```bash
cd services/web-ui
npm test -- --testPathPattern="proxy-auth"
```

Expected: PASS.

- [ ] **Step 8: Run full web UI test suite**

```bash
cd services/web-ui
npm test
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add services/web-ui/app/api/proxy/ \
        services/web-ui/__tests__/proxy-auth.test.ts \
        services/web-ui/.env.example
git commit -m "feat(web-ui): forward Authorization header from browser to API gateway on all proxy routes (CONCERNS 1.3)"
```

---

## Chunk 3: Remove Hardcoded Prod URLs (Task 11-03)

### Task 11-03: Remove Hardcoded Prod URL Fallbacks

**Files:** Same 5 proxy routes (already updated in 11-02 via `getApiGatewayUrl()`)
**Dependency:** 11-02 must be complete first — the `getApiGatewayUrl()` helper in 11-02 already implements the "throw on missing URL" behavior required by 11-03.

- [ ] **Step 1: Verify no prod URL string remains in proxy routes**

```bash
grep -r "wittypebble" services/web-ui/
```

Expected: No matches. The `getApiGatewayUrl()` implementation in Task 11-02 already removes the hardcoded URL.

- [ ] **Step 2: Write test confirming 500 when `API_GATEWAY_URL` unset in non-dev mode**

Add to `services/web-ui/__tests__/proxy-auth.test.ts`:

```typescript
describe('Chat proxy: API_GATEWAY_URL validation', () => {
  beforeEach(() => {
    delete process.env.API_GATEWAY_URL;
    process.env.NEXT_PUBLIC_DEV_MODE = 'false';
    jest.resetModules();
  });

  it('returns 502 when API_GATEWAY_URL is unset and not in dev mode', async () => {
    const { POST } = await import('../app/api/proxy/chat/route');

    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    });

    const response = await POST(incomingRequest as any);
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error).toContain('API_GATEWAY_URL is not configured');
  });

  it('defaults to localhost:8000 in dev mode when API_GATEWAY_URL unset', async () => {
    process.env.NEXT_PUBLIC_DEV_MODE = 'true';
    jest.resetModules();

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ thread_id: 'th_123' }),
    } as Response);

    const { POST } = await import('../app/api/proxy/chat/route');
    const incomingRequest = new Request('http://localhost:3000/api/proxy/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    });

    await POST(incomingRequest as any);

    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/chat',
      expect.anything()
    );
  });
});
```

- [ ] **Step 3: Run the new tests**

```bash
cd services/web-ui
npm test -- --testPathPattern="proxy-auth"
```

Expected: All tests PASS.

- [ ] **Step 4: Confirm no prod URL in source**

```bash
grep -r "wittypebble" . --include="*.ts" --include="*.tsx" --include="*.js"
```

Expected: Zero matches.

- [ ] **Step 5: Commit**

```bash
git add services/web-ui/__tests__/proxy-auth.test.ts
git commit -m "test(web-ui): add tests for API_GATEWAY_URL validation and missing URL 502 (CONCERNS 2.1)"
```

---

## Chunk 4: Fix SSE Route Internal Poll URL (Task 11-04)

### Task 11-04: Fix Hardcoded `localhost:3000` in SSE Stream Route

**Files:**
- Modify: `services/web-ui/app/api/stream/route.ts`

**Context:** Line 120 of `stream/route.ts` polls `http://localhost:3000/api/proxy/chat/result?...`. In production Container Apps, the app runs on a non-localhost FQDN. Node.js `fetch` requires absolute URLs — relative paths throw `TypeError: Failed to parse URL`. The fix uses `NEXT_PUBLIC_SITE_URL` env var with `http://localhost:3000` as dev fallback.

- [ ] **Step 1: Write failing test**

Create `services/web-ui/__tests__/stream-poll-url.test.ts`:

```typescript
/**
 * Tests: SSE stream route uses NEXT_PUBLIC_SITE_URL for internal polling.
 * Verifies that the hardcoded localhost:3000 is replaced with the env var.
 */
import { describe, it, expect, jest, beforeEach } from '@jest/globals';

describe('SSE stream route: internal poll URL', () => {
  beforeEach(() => {
    jest.resetModules();
    global.fetch = jest.fn() as any;
  });

  it('uses NEXT_PUBLIC_SITE_URL as base URL for internal poll', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://ca-web-ui-prod.example.azurecontainerapps.io';

    // Mock fetch to return a completed result on first call, stopping the polling loop
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        thread_id: 'th_123',
        run_status: 'completed',
        reply: 'Done',
      }),
    } as Response);

    const { GET } = await import('../app/api/stream/route');

    const url = new URL('http://localhost:3000/api/stream?thread_id=th_123&type=token');
    const req = new Request(url.toString());

    // Start the SSE stream (it will poll once and complete)
    const response = await GET(req as any);
    expect(response.status).toBe(200);

    // Verify the fetch was called with the NEXT_PUBLIC_SITE_URL base
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('https://ca-web-ui-prod.example.azurecontainerapps.io/api/proxy/chat/result'),
      expect.anything()
    );

    // Verify localhost:3000 NOT in the poll URL
    const fetchUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(fetchUrl).not.toContain('localhost:3000');
  });

  it('falls back to localhost:3000 when NEXT_PUBLIC_SITE_URL is not set', async () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ thread_id: 'th_123', run_status: 'completed', reply: 'Done' }),
    } as Response);

    const { GET } = await import('../app/api/stream/route');
    const url = new URL('http://localhost:3000/api/stream?thread_id=th_123&type=token');
    const req = new Request(url.toString());

    await GET(req as any);

    const fetchUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(fetchUrl).toContain('http://localhost:3000/api/proxy/chat/result');
  });
});
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd services/web-ui
npm test -- --testPathPattern="stream-poll-url"
```

Expected: FAIL — poll URL still hardcodes `localhost:3000`.

- [ ] **Step 3: Fix `stream/route.ts` — replace hardcoded base URL**

Find this line in `services/web-ui/app/api/stream/route.ts` (line ~120):

```typescript
const res = await fetch(
  `http://localhost:3000/api/proxy/chat/result?thread_id=${encodeURIComponent(threadId)}${runIdParam}`,
  { signal: AbortSignal.timeout(8000) }
);
```

Replace with:

```typescript
const siteBase = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000';
const res = await fetch(
  `${siteBase}/api/proxy/chat/result?thread_id=${encodeURIComponent(threadId)}${runIdParam}`,
  { signal: AbortSignal.timeout(8000) }
);
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd services/web-ui
npm test -- --testPathPattern="stream-poll-url"
```

Expected: PASS.

- [ ] **Step 5: Verify `localhost:3000` string is gone from stream route**

```bash
grep -n "localhost:3000" services/web-ui/app/api/stream/route.ts
```

Expected: No matches.

- [ ] **Step 6: Commit**

```bash
git add services/web-ui/app/api/stream/route.ts \
        services/web-ui/__tests__/stream-poll-url.test.ts
git commit -m "fix(web-ui): replace hardcoded localhost:3000 with NEXT_PUBLIC_SITE_URL in SSE stream route (CONCERNS 2.2)"
```

---

## Chunk 5: Arc MCP E2E URL Variable (Task 11-05)

### Task 11-05: Verify and Document Arc MCP E2E URL Variable

**Files:**
- Verify: `e2e/arc-mcp-server.spec.ts`
- Check: `e2e/README.md` (document env var)

**Context:** The spec referenced `E2E_ARC_MCP_URL` but the existing code already uses `ARC_MCP_SERVER_URL` at line 27. We need to verify the current state, close BACKLOG F-06 if resolved, and document the env var.

- [ ] **Step 1: Verify the current env var name in the spec**

```bash
grep -n "ARC_MCP" e2e/arc-mcp-server.spec.ts
```

Expected output:
```
27:const ARC_MCP_SERVER_URL = process.env.ARC_MCP_SERVER_URL || 'http://localhost:8080';
```

This confirms `ARC_MCP_SERVER_URL` is already the env var name. No code change is needed to the spec.

- [ ] **Step 2: Check if e2e README exists; create/update it**

```bash
ls e2e/README.md 2>/dev/null || echo "File does not exist"
```

- [ ] **Step 3: Document env vars in e2e README**

If `e2e/README.md` does not exist, create it. If it exists, add the missing env var documentation:

```markdown
## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARC_MCP_SERVER_URL` | Yes (non-local) | `http://localhost:8080` | URL of the Arc MCP Server Container App |
| `API_GATEWAY_URL` | Yes (non-local) | `http://localhost:8000` | URL of the API gateway Container App |
| `TEST_SUBSCRIPTION_ID` | E2E-006 | `sub-e2e-test-001` | Subscription ID used in mock ARM seeding |
| `TEST_AUTH_TOKEN` | E2E-006 | `test-token` | Bearer token for API gateway authentication |
| `ARC_SEEDED_COUNT` | E2E-006 | `120` | Number of Arc servers seeded in mock ARM |
```

- [ ] **Step 4: Verify tests pass locally (connectivity test)**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
npx playwright test e2e/arc-mcp-server.spec.ts --grep "health check" --timeout 10000 2>&1 | tail -20
```

If Arc MCP server is not running locally, this will fail with a connection error — that is expected and acceptable. The test code itself is correct.

- [ ] **Step 5: Commit**

```bash
git add e2e/README.md
git commit -m "docs(e2e): document ARC_MCP_SERVER_URL and other e2e environment variables; close BACKLOG F-06 (CONCERNS 2.3)"
```

---

## Verification Checklist

- [ ] `python -m pytest services/api-gateway/tests/ -v` — all tests pass, including new rate limiter tests
- [ ] `cd services/web-ui && npm test` — all tests pass, including new proxy-auth and stream-poll-url tests
- [ ] `grep -r "wittypebble" services/` — zero matches
- [ ] `grep -rn "localhost:3000" services/web-ui/app/api/stream/route.ts` — zero matches
- [ ] `grep -n "ARC_MCP_SERVER_URL" e2e/arc-mcp-server.spec.ts` — confirms correct env var name in use
- [ ] `grep "API_GATEWAY_URL" services/web-ui/.env.example` — env var documented
- [ ] `grep "NEXT_PUBLIC_SITE_URL" services/web-ui/.env.example` — env var documented
