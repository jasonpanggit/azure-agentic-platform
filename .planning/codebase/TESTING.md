# Testing — Azure Agentic Platform

> Extracted from codebase inspection. Last updated: 2026-03-30.

---

## 1. Test Frameworks

| Language | Framework | Version | Config file |
|---|---|---|---|
| Python | **pytest** | latest | `pyproject.toml` `[tool.pytest.ini_options]` |
| TypeScript (Teams Bot) | **Vitest** | latest | `services/teams-bot/vitest.config.ts` |
| TypeScript (Web UI) | **Jest** (unit) + **Playwright** (E2E) | Playwright 1.58.x | `e2e/playwright.config.ts` |
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

services/api-gateway/tests/
    conftest.py
    test_approval_lifecycle.py
    test_audit_export.py
    test_audit_trail.py
    test_auth_security.py
    test_chat_endpoint.py
    test_gitops_path.py
    test_health.py
    test_incidents.py
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

### TypeScript (Teams Bot)

Tests are co-located in `__tests__/` subdirectories next to the source files:

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

### Web UI

```
services/web-ui/__tests__/
    auth.test.tsx     # (mostly skipped — placeholder)
    layout.test.tsx   # (mostly skipped — placeholder)
```

### E2E

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

## 3. Types of Tests

### Unit Tests (Python)

Marked `@pytest.mark.unit`. Fast, no external dependencies. Test individual
functions, classes, and data transformations in isolation.

**Examples:**
- `test_envelope.py` — validates `IncidentMessage` TypedDict structure and `validate_envelope()`
- `test_classify_domain.py` — parametrized table tests for ARM resource type → domain mapping
- `test_rate_limiting.py` — sliding window rate limiter logic
- `test_dedup.py` — deduplication fingerprint and window logic
- `test_payload_mapper.py` — Event Hubs payload → Cosmos DB model mapping
- `test_alert_state.py` — state machine transition validation

**Pattern:**

```python
class TestClassifyDomainExactMatches:
    @pytest.mark.parametrize("resource_type,expected_domain", [
        ("Microsoft.Compute/virtualMachines", "compute"),
        ...
    ])
    def test_exact_match(self, resource_type: str, expected_domain: str) -> None:
        assert classify_domain(resource_type) == expected_domain
```

### Integration Tests (Python)

Marked `@pytest.mark.integration`. Test module interactions and data contracts.
Most run without real Azure services (mocked with `unittest.mock`). A subset
requires live Azure credentials (runs only on `push` to `main`).

**Examples:**
- `test_triage.py` — `TriageDiagnosis` and `RemediationProposal` structure validation, including envelope serialisation
- `test_budget.py` — `BudgetTracker` with mocked Cosmos containers
- `test_handoff.py` — agent handoff envelope contract
- `test_remediation.py` — full remediation proposal-to-approval flow
- `test_chat_endpoint.py` — FastAPI `TestClient` tests with mocked Foundry + Cosmos

### Unit Tests (TypeScript / Vitest)

All TypeScript unit tests use Vitest. Located in `__tests__/` folders co-located with source. Integration tests are explicitly excluded from the default run.

**Examples:**
- `approval-card.test.ts` — card schema, action types (`Action.Execute` not `Action.Http`), risk colors
- `gateway-client.test.ts` — HTTP client retry and error handling
- `bot.test.ts` — bot activity routing
- `config.test.ts` — env var validation

**Pattern:**
```typescript
describe("buildApprovalCard", () => {
  it("actions use Action.Execute (NOT Action.Http)", () => {
    const card = buildApprovalCard(basePayload);
    const actions = card.actions as Record<string, unknown>[];
    for (const action of actions) {
      expect(action.type).toBe("Action.Execute");
    }
  });
});
```

### E2E Tests (Playwright)

Run against real deployed Container Apps. No mocks. Require env vars:
`E2E_BASE_URL`, `E2E_API_URL`, `E2E_CLIENT_ID`, `E2E_CLIENT_SECRET`, `E2E_TENANT_ID`.

**Timeout:** 120 seconds per test (`timeout: 120_000` in config); agent triage tests use `TRIAGE_TIMEOUT_MS = 90_000`.

**Coverage:**
- `e2e-incident-flow.spec.ts` — POST incident → thread dispatch → SSE stream
- `e2e-hitl-approval.spec.ts` — approve/reject flow end-to-end
- `e2e-rbac.spec.ts` — authentication/authorization enforcement
- `e2e-sse-reconnect.spec.ts` — SSE reconnect continuity
- `e2e-audit-export.spec.ts` — audit export endpoint
- `e2e-teams-roundtrip.spec.ts` — Teams bot → API gateway roundtrip
- `arc-mcp-server.spec.ts` — Arc MCP tool calls against real Arc resources
- `sc1/sc2/sc5/sc6.spec.ts` — explicit success criteria validation

---

## 4. Coverage

### Python — Enforced at 80%

Coverage is measured and enforced by CI with `--cov-fail-under=80`:

```bash
pytest services/api-gateway/tests/ agents/shared/ \
    --ignore=tests/integration \
    --cov=services/api-gateway --cov=agents/shared \
    --cov-report=xml --cov-report=term-missing \
    --cov-fail-under=80
```

Coverage is uploaded as a CI artifact (`coverage.xml`).

**Well-covered areas:**
- `services/api-gateway/` — comprehensive test suite (17 test files covering every module)
- `agents/shared/` — envelope, triage, budget, routing all have dedicated tests
- `services/detection-plane/` — 6 unit test modules + 6 integration test modules
- `services/arc-mcp-server/` — 4 test files covering all 3 tool categories + pagination

**Under-covered / gaps:**
- `services/web-ui/` — `__tests__/auth.test.tsx` and `layout.test.tsx` contain only `it.skip()` placeholder tests (TODO: Plan 05-01)
- `agents/*/agent.py` — agent factory functions are not unit-tested; they require the real `agent_framework` RC package
- `scripts/` — utility scripts (`configure-orchestrator.py`, `seed.py`, `simulate-incidents/`) have no tests
- `fabric/user-data-function/` — covered only in detection-plane unit tests via `test_user_data_function.py`

### TypeScript / Vitest — Enforced at 80%

```bash
npx vitest run --coverage --coverage.thresholds.lines=80 --exclude='**/integration/**'
```

Coverage provider: v8. Reporters: text, json, html. Integration tests are excluded from the threshold check.

---

## 5. Mocking Patterns

### Python — `unittest.mock`

**Standard approach:** `unittest.mock.patch()` as context manager or via `@patch` decorator.

```python
with patch(
    "services.api_gateway.chat._get_foundry_client",
    return_value=mock_foundry,
), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
    response = client.post("/api/v1/chat", json={"message": "check vm-prod-01"})
```

**Async mocks:** `unittest.mock.AsyncMock` for coroutines:

```python
mock_teams_notifier = AsyncMock()
mock_teams_notifier.post_card.return_value = {"message_id": "teams-msg-001"}
```

**Cosmos DB mocking:** `MagicMock` instances with `query_items`, `read_item`, `replace_item`, `create_item` configured in conftest fixtures.

**Environment variable mocking:** `patch.dict("os.environ", {...})` for per-test env var isolation.

### Key conftest.py Fixtures (api-gateway)

| Fixture | Type | Purpose |
|---|---|---|
| `client` | `TestClient` | FastAPI test client with `API_GATEWAY_AUTH_MODE=disabled` |
| `mock_foundry_client` | `MagicMock` | AIProjectClient with `agents.create_thread/message/run` |
| `mock_cosmos_approvals` | `MagicMock` | Cosmos container with realistic approval record |
| `mock_cosmos_incidents` | `MagicMock` | Cosmos container with incident records |
| `mock_teams_notifier` | `AsyncMock` | Teams card poster |
| `mock_arm_client` | `MagicMock` | ARM resource client for Resource Identity tests |
| `sample_approval_record` | `dict` | Pre-built D-12 schema approval record |
| `sample_remediation_proposal` | `RemediationProposal` | Pre-built proposal for approval tests |
| `pre_seeded_embeddings` | `list[list[float]]` | 3 deterministic 1536-dim unit vectors for RAG tests (no Azure OpenAI call) |

### Arc MCP Server conftest.py Fixtures

| Fixture | Purpose |
|---|---|
| `sample_machines_120` | 120 mock `HybridCompute Machine` objects for pagination tests |
| `sample_clusters_105` | 105 mock `ConnectedCluster` objects for K8s pagination tests |
| Helper `_make_machine()`, `_make_cluster()`, `_make_extension()` | MagicMock factories with realistic ARM IDs and property shapes |

### Root conftest.py — Agent Framework Stub

`conftest.py` at the project root installs a lightweight `agent_framework` stub into
`sys.modules` so agent source files can be imported during tests without the pre-release
RC package:

```python
# Provides: ChatAgent, HandoffOrchestrator, AgentTarget, @ai_function
# Real framework behaviour not needed for unit/integration tests
```

It also registers hyphenated service paths as importable Python packages:
`services/api-gateway/` → `services.api_gateway`.

### TypeScript Mocking (Vitest)

Vitest `vi.mock()` and factory functions. Integration tests in `**/integration/**` are
excluded from the unit test run and coverage gate.

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

**pytest discovery config:**

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

### Python Test Command (all CI)

```bash
pytest services/api-gateway/tests/ agents/shared/ \
    --ignore=tests/integration \
    -v --tb=short \
    --cov=services/api-gateway --cov=agents/shared \
    --cov-report=xml --cov-report=term-missing \
    --cov-fail-under=80
```

Python version: 3.12 (API gateway), 3.11 (detection-plane).

### TypeScript Test Command (Teams Bot)

```bash
npm run lint
npm run typecheck
npx vitest run --coverage --coverage.thresholds.lines=80 --exclude='**/integration/**'
```

### Playwright E2E Command (Web UI CI)

```bash
npx playwright test --project=chromium --reporter=github
```

Runs Chromium only in CI. Tests run sequentially (`workers: 1`, `fullyParallel: false`)
to preserve state isolation. 2 retries on failure in CI.

### Integration Test Gating

Detection-plane integration tests only run on `push` to `main` (after unit tests pass),
require the `staging` environment, and need live Azure credentials:
`COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME`, `EVENTHUB_CONNECTION_STRING`.

### Coverage Artifacts

- Python: `coverage.xml` uploaded via `actions/upload-artifact@v4`
- TypeScript: `services/teams-bot/coverage/` directory uploaded
- Playwright: `playwright-report/` uploaded on every run (including failure)

---

## 8. Missing Test Areas

| Area | Current Status | Gap |
|---|---|---|
| Web UI components | `auth.test.tsx`, `layout.test.tsx` contain only `it.skip()` stubs | No component tests exist; marked TODO Plan 05-01 |
| Agent factory functions | Not tested | `create_compute_agent()`, etc. require real `agent_framework` RC — stub only provides no-ops |
| `agents/*/agent.py` system prompts | Not validated | Prompt content and `{allowed_tools}` injection not asserted |
| `services/arc-mcp-server/auth.py` | Not confirmed | Auth module exists but no dedicated auth test file |
| `scripts/` utilities | No test files | `configure-orchestrator.py`, `seed.py`, `validate.py`, simulation scenarios |
| Fabric `user-data-function/main.py` | Partially via detection-plane unit tests | Entry point HTTP handler not independently tested |
| Cross-agent integration | Agent handoff tests use mocked framework | No live multi-agent conversation tests outside E2E |
| Token budget enforcement under concurrency | Unit tests cover happy path | No concurrent write / ETag conflict tests for `BudgetTracker` |
| SSE stream format | `test_sse_stream.py` present | Not confirmed what it covers — may be thin |
