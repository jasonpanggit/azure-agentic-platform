# Testing — Azure Agentic Platform

> Extracted from codebase inspection. Last updated: 2026-04-01.

---

## 1. Test Frameworks

| Language | Framework | Version | Config file |
|---|---|---|---|
| Python | **pytest** | latest | `pyproject.toml` `[tool.pytest.ini_options]` |
| TypeScript (Teams Bot) | **Vitest** | latest | `services/teams-bot/vitest.config.ts` |
| TypeScript (Web UI) | **Jest** (unit) | latest | `services/web-ui/jest.config.js` |
| E2E (cross-service) | **Playwright** | 1.58.x | `e2e/playwright.config.ts` |

---

## 2. Test File Locations and Naming

### Python

Tests are co-located with services in `tests/` subdirectories:

```
agents/tests/
    shared/
        test_budget.py
        test_envelope.py
    integration/
        test_arc_triage.py
        test_budget.py
        test_handoff.py
        test_mcp_tools.py
        test_remediation.py
        test_triage.py

services/api-gateway/tests/           # 166 tests
    conftest.py
    test_approval_lifecycle.py
    test_approvals_404.py
    test_audit_export.py
    test_audit_trail.py
    test_auth_security.py
    test_chat_endpoint.py
    test_dependencies.py
    test_gitops_path.py
    test_health.py
    test_health_ready.py
    test_http_rate_limiter.py
    test_incidents.py
    test_incidents_list.py
    test_patch_endpoints.py
    test_rate_limiting.py
    test_remediation_logger.py
    test_resource_identity.py
    test_runbook_rag.py
    test_runbook_search_availability.py
    test_sse_heartbeat.py
    test_sse_stream.py
    test_teams_notifier.py

services/arc-mcp-server/tests/
    conftest.py
    test_arc_data.py
    test_arc_k8s.py
    test_arc_servers.py
    test_pagination.py

services/detection-plane/tests/
    unit/
        test_alert_state.py
        test_classify_domain.py
        test_dedup.py
        test_kql_pipeline.py
        test_payload_mapper.py
        test_user_data_function.py
    integration/
        test_activity_log.py
        test_dedup_load.py
        test_pipeline_flow.py
        test_round_trip.py
        test_state_sync.py
        test_suppression.py
```

**Naming rule:** `test_<module_or_feature>.py`. Test classes are `Test<Feature>`, test functions are `test_<scenario>`.

### TypeScript (Teams Bot — Vitest)

Tests co-located in `__tests__/` subdirectories next to source files:

```
services/teams-bot/src/
    __tests__/
        bot.test.ts
        config.test.ts
        integration/
            teams-e2e-stubs.test.ts
    cards/__tests__/
        alert-card.test.ts
        approval-card.test.ts
        outcome-card.test.ts
        reminder-card.test.ts
    routes/__tests__/
        health.test.ts
        notify.test.ts
    services/__tests__/
        auth.test.ts
        conversation-state.test.ts
        escalation.test.ts
        gateway-client.test.ts
        proactive.test.ts
```

### TypeScript (Web UI — Jest)

```
services/web-ui/
    __tests__/
        auth.test.tsx
        proxy-auth.test.ts
        stream-poll-url.test.ts
        stream.test.ts
        useAuth.test.tsx
    lib/__tests__/
        format-relative-time.test.ts
    __mocks__/
        next-server.ts         # Manual mock for next/server
```

Jest config: `services/web-ui/jest.config.js` — uses `ts-jest` preset, `testEnvironment: 'node'`,
`@/` path alias mapped to `<rootDir>/`.

### E2E (Playwright)

```
e2e/
    e2e-audit-export.spec.ts
    e2e-hitl-approval.spec.ts
    e2e-incident-flow.spec.ts
    e2e-rbac.spec.ts
    e2e-sse-reconnect.spec.ts
    e2e-teams-roundtrip.spec.ts
    arc-mcp-server.spec.ts
    sc1.spec.ts   # Success Criterion 1: FMP + first token latency
    sc2.spec.ts   # Success Criterion 2: SSE reconnect continuity
    sc5.spec.ts   # Success Criterion 5: Resource Identity Certainty
    sc6.spec.ts   # Success Criterion 6: GitOps vs direct-apply path
    fixtures/auth.ts
    global-setup.ts
    global-teardown.ts
```

---

## 3. Test Count and Coverage

### Total Test Count

| Scope | Framework | Count |
|---|---|---|
| Python (all services + agents) | pytest | **432 tests** (2 collection errors in arc-mcp-server + detection-plane due to path mismatch; 430 run cleanly) |
| API gateway only | pytest | **166 tests** |
| Teams Bot | Vitest | ~14 test files |
| Web UI | Jest | 6 test files (stream, auth, proxy, lib utility) |
| E2E | Playwright | 10 spec files |

### Coverage Enforcement

- **Python:** `--cov-fail-under=80` enforced in CI for `services/api-gateway` + `agents/shared`
- **TypeScript (Teams Bot):** `--coverage.thresholds.lines=80` in Vitest; integration tests excluded
- **Web UI:** Coverage not enforced (Jest used for unit tests only; E2E covers critical flows via Playwright)

### Well-Covered Areas

- `services/api-gateway/` — 23 test files, 166 tests covering every endpoint and module
- `agents/shared/` — envelope, triage, budget, routing all have dedicated unit tests
- `services/detection-plane/` — 6 unit + 6 integration test modules
- `services/arc-mcp-server/` — 4 test files covering all 3 tool categories + pagination
- Web UI streaming — SSE heartbeat and stream format covered by both Python (`test_sse_stream.py`) and Jest (`stream.test.ts`)

---

## 4. How to Run Tests

### Python — All Tests

```bash
# From project root
python3 -m pytest -v --tb=short
```

### Python — API Gateway Only (with coverage)

```bash
pytest services/api-gateway/tests/ agents/shared/ \
    --ignore=tests/integration \
    -v --tb=short \
    --cov=services/api-gateway --cov=agents/shared \
    --cov-report=xml --cov-report=term-missing \
    --cov-fail-under=80
```

### Python — Detection Plane (unit only)

```bash
pytest services/detection-plane/tests/unit/ -v --tb=short
```

### Python — Integration Tests (requires Azure credentials)

```bash
pytest services/ agents/ -m integration -v --tb=short
```

### TypeScript — Teams Bot (Vitest)

```bash
cd services/teams-bot
npm run test             # vitest run --coverage
npm run test:watch       # vitest (interactive)
```

### TypeScript — Web UI (Jest)

```bash
cd services/web-ui
npm test                 # jest
```

### E2E — Playwright

```bash
# Requires: E2E_BASE_URL, E2E_API_URL, E2E_CLIENT_ID, E2E_CLIENT_SECRET, E2E_TENANT_ID
cd e2e
npx playwright test --project=chromium
```

---

## 5. Test Patterns Used

### Python: Class-Based Grouping with Descriptive Methods

```python
class TestChatEndpoint:
    """Tests for POST /api/v1/chat endpoint."""

    def test_valid_chat_creates_thread(self, client):
        """POST /api/v1/chat returns 202 with thread_id."""
        ...

    def test_chat_requires_message(self, client):
        """POST /api/v1/chat without message returns 422."""
        ...
```

- Test class names: `Test<Feature>` (e.g., `TestApprovalLifecycle`, `TestChatEndpoint`)
- Method names describe the **scenario and expected outcome** in plain English
- Docstrings on every test method — single sentence explaining what is asserted

### Python: FastAPI TestClient + Disabled Auth

```python
# conftest.py — auth bypassed for all API gateway tests
os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

@pytest.fixture()
def client():
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = MagicMock(name="CosmosClient")
    return TestClient(app)
```

### Python: patch() for Dependency Isolation

```python
with patch(
    "services.api_gateway.chat._get_foundry_client",
    return_value=mock_foundry,
), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
    response = client.post("/api/v1/chat", json={"message": "check vm-prod-01"})
```

- `patch()` used as a context manager (preferred over decorator for co-located assertions)
- `patch.dict("os.environ", {...})` for per-test env var isolation
- Module path patched is the **consumer's import path** (not the source module path)

### Python: AsyncMock for Coroutines

```python
mock_teams_notifier = AsyncMock()
mock_teams_notifier.post_card.return_value = {"message_id": "teams-msg-001"}
```

`unittest.mock.AsyncMock` used for all async function mocks. Sync mocks use `MagicMock`.

### Python: Shared conftest.py Fixtures

| Fixture | Type | Purpose |
|---|---|---|
| `client` | `TestClient` | FastAPI test client with `API_GATEWAY_AUTH_MODE=disabled` |
| `mock_foundry_client` | `MagicMock` | AIProjectClient with `agents.create_thread/message/run` |
| `mock_cosmos_approvals` | `MagicMock` | Cosmos container with realistic D-12 schema approval record |
| `mock_cosmos_incidents` | `MagicMock` | Cosmos container with incident records |
| `mock_teams_notifier` | `AsyncMock` | Teams card poster |
| `mock_arm_client` | `MagicMock` | ARM resource client for Resource Identity tests |
| `sample_approval_record` | `dict` | Pre-built D-12 schema approval record |
| `sample_remediation_proposal` | `RemediationProposal` | Pre-built proposal for approval lifecycle tests |
| `pre_seeded_embeddings` | `list[list[float]]` | 3 deterministic 1536-dim unit vectors (seed=42, no Azure OpenAI call) |

### Python: Root conftest.py — Agent Framework Stub

`conftest.py` at the project root installs a lightweight `agent_framework` stub into
`sys.modules` so agent source files can be imported during tests without the pre-release
RC package:

```python
# Provides: ChatAgent, HandoffOrchestrator, AgentTarget, @ai_function
# Real framework behaviour not needed for unit/integration tests
```

It also registers hyphenated service paths as importable Python packages:
`services/api-gateway/` → `services.api_gateway`.

### Python: Parametrize for Table-Driven Tests

```python
@pytest.mark.parametrize("resource_type,expected_domain", [
    ("Microsoft.Compute/virtualMachines", "compute"),
    ("Microsoft.Network/virtualNetworks", "network"),
    ...
])
def test_exact_match(self, resource_type: str, expected_domain: str) -> None:
    assert classify_domain(resource_type) == expected_domain
```

Used extensively in `test_classify_domain.py` and payload validation tests.

### Python: Async Tests

```python
@pytest.mark.asyncio
async def test_get_chat_result_with_run_id_targets_specific_run(self):
    ...
    result = await get_chat_result("thread-123", run_id="run-specific")
    assert result["run_status"] == "queued"
```

`pytest-asyncio` (or `anyio`) used for async tests. Some older tests use
`asyncio.get_event_loop().run_until_complete(...)` directly.

### TypeScript: Vitest with vi.mock() (Teams Bot)

```typescript
vi.mock("../services/gateway-client", () => ({
  GatewayClient: vi.fn(),
}));

describe("AapTeamsBot", () => {
  let bot: AapTeamsBot;
  let gateway: ReturnType<typeof createMockGateway>;

  beforeEach(() => {
    vi.clearAllMocks();
    gateway = createMockGateway();
    bot = new AapTeamsBot(gateway as any);
  });
  ...
});
```

- `vi.mock()` at module top, before imports
- `vi.clearAllMocks()` in `beforeEach` to reset state
- Factory functions (`createMockContext()`, `createMockGateway()`) for reusable test doubles

### TypeScript: Jest with Fake Timers (Web UI)

```typescript
describe('SSE stream route: heartbeat', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.resetModules();
    global.fetch = jest.fn() as any;
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('emits ": heartbeat" after 20-second interval', async () => {
    await jest.advanceTimersByTimeAsync(21_000);
    const firstRead = await reader.read();
    expect(decoder.decode(firstRead.value)).toContain(': heartbeat');
  });
});
```

- `jest.useFakeTimers()` + `jest.advanceTimersByTimeAsync()` for time-dependent SSE tests
- `jest.resetModules()` ensures fresh module imports per test
- `global.fetch` manually mocked (no jest-fetch-mock dependency)

---

## 6. pytest Markers

Defined in `pyproject.toml`:

| Marker | Meaning |
|---|---|
| `unit` | Fast, no external dependencies |
| `integration` | Require mocked or real external services |
| `slow` | Takes more than 10 seconds |
| `e2e` | End-to-end with Playwright |
| `sc1` | Success Criterion 1: FMP + first token latency |
| `sc2` | Success Criterion 2: SSE reconnect continuity |
| `sc3` | Success Criterion 3: Runbook RAG similarity + latency |
| `sc4` | Success Criterion 4: HITL gate lifecycle |
| `sc5` | Success Criterion 5: Resource Identity Certainty |
| `sc6` | Success Criterion 6: GitOps vs direct-apply path |

**pytest discovery config (`pyproject.toml`):**

```toml
[tool.pytest.ini_options]
testpaths = ["agents", "services"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
pythonpath = ["."]
```

---

## 7. CI Test Execution

### Workflows and Triggers

| Workflow | File | Trigger | Tests Run |
|---|---|---|---|
| API Gateway + Web UI CI | `api-gateway-web-ui-ci.yml` | Push/PR to `services/api-gateway/**`, `services/web-ui/**`, `agents/shared/**`, `e2e/**` | Python unit (80% gate) + Playwright E2E |
| Teams Bot + API Gateway CI | `teams-bot-api-gateway-ci.yml` | Push/PR to `services/teams-bot/**`, `services/api-gateway/**` | Vitest unit (80% gate) + Python unit |
| Detection Plane CI | `detection-plane-ci.yml` | Push/PR to `services/detection-plane/**`, `fabric/**` | Python unit + ruff lint; integration only on `push` to `main` |

### Python Test Command (CI)

```bash
pytest services/api-gateway/tests/ agents/shared/ \
    --ignore=tests/integration \
    -v --tb=short \
    --cov=services/api-gateway --cov=agents/shared \
    --cov-report=xml --cov-report=term-missing \
    --cov-fail-under=80
```

Python versions: 3.12 (API gateway), 3.11 (detection-plane).

### TypeScript Test Commands

```bash
# Teams Bot (Vitest)
npm run lint
npm run typecheck
npx vitest run --coverage --coverage.thresholds.lines=80 --exclude='**/integration/**'

# Web UI (Jest)
cd services/web-ui && npm test
```

### Playwright E2E Command

```bash
npx playwright test --project=chromium --reporter=github
```

Chromium only in CI. Sequential workers (`workers: 1`, `fullyParallel: false`) for state isolation.
2 retries on failure. Timeout: 120 seconds per test.

### Integration Test Gating

Detection-plane integration tests only run on `push` to `main` (after unit tests pass),
require the `staging` environment, and need live Azure credentials:
`COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME`, `EVENTHUB_CONNECTION_STRING`.

### Coverage Artifacts

- Python: `coverage.xml` uploaded via `actions/upload-artifact@v4`
- TypeScript: `services/teams-bot/coverage/` directory uploaded
- Playwright: `playwright-report/` uploaded on every run (including failure)

---

## 8. Gaps / Missing Coverage

| Area | Current Status | Gap |
|---|---|---|
| Web UI components | `auth.test.tsx`, `useAuth.test.tsx` exist but `proxy-auth`, `stream`, `stream-poll-url` are relatively new | No React component render tests (only route/util logic tested) |
| Agent factory functions | Not tested | `create_compute_agent()` etc. require real `agent_framework` RC; stub only provides no-ops |
| `agents/*/agent.py` system prompts | Not validated | Prompt content and `{allowed_tools}` injection not asserted |
| `services/arc-mcp-server/auth.py` | No dedicated test file | Auth module exists but not independently tested |
| `scripts/` utilities | No test files | `configure-orchestrator.py`, `seed.py`, `validate.py`, simulation scenarios |
| Fabric `user-data-function/main.py` | Partially via detection-plane unit tests | Entry point HTTP handler not independently tested |
| Cross-agent integration | Agent handoff tests use mocked framework | No live multi-agent conversation tests outside Playwright E2E |
| Token budget concurrency | Unit tests cover happy path | No concurrent write / ETag conflict tests for `BudgetTracker` |
| arc-mcp-server + detection-plane | `pytest --collect-only` shows 2 `ImportPathMismatchError` errors | These services have separate `pyproject.toml` files causing path conflicts when run from repo root; run from their own directories |
