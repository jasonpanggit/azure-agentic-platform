# Code Conventions — Azure Agentic Platform

> Extracted from codebase inspection. Last updated: 2026-04-01.

---

## 1. Naming Conventions

### Files

| Context | Pattern | Examples |
|---|---|---|
| Python source modules | `snake_case.py` | `approval_manager.py`, `classify_domain.py`, `runbook_rag.py` |
| Python test files | `test_<module>.py` | `test_chat_endpoint.py`, `test_rate_limiting.py` |
| TypeScript source | `kebab-case.ts` / `camelCase.ts` | `approval-card.ts`, `gateway-client.ts` |
| TypeScript test files | `<module>.test.ts` in `__tests__/` | `approval-card.test.ts`, `bot.test.ts` |
| E2E spec files | `e2e-<scenario>.spec.ts` or `sc<N>.spec.ts` | `e2e-incident-flow.spec.ts`, `sc1.spec.ts` |
| Service directories | `kebab-case/` | `api-gateway/`, `arc-mcp-server/`, `teams-bot/` |

**Note:** Hyphenated service directories (`services/api-gateway/`) are registered as
underscore-namespaced Python packages (`services.api_gateway`) in the root `conftest.py`.

### Python Variables and Functions

- **Variables/functions:** `snake_case` — e.g., `correlation_id`, `query_activity_log`, `check_and_record`
- **Classes:** `PascalCase` — e.g., `TriageDiagnosis`, `RemediationProposal`, `BudgetTracker`, `EntraTokenValidator`
- **Constants:** `UPPER_SNAKE_CASE` — e.g., `ALLOWED_MCP_TOOLS`, `VALID_MESSAGE_TYPES`, `DEFAULT_MAX_ITERATIONS`, `SESSIONS_CONTAINER_NAME`
- **Private helpers:** `_snake_case` prefix — e.g., `_get_foundry_client`, `_first_matching_keyword`, `_read_auth_mode`, `_run_startup_migrations`

### TypeScript Variables and Functions

- **Variables/functions:** `camelCase` — e.g., `getRiskColor`, `buildApprovalCard`, `gatewayClient`
- **Types/Interfaces:** `PascalCase` — e.g., `ApprovalPayload`, `ApprovalCard`
- **Constants:** `UPPER_SNAKE_CASE` for module-level, `camelCase` for function-scoped

### Agent Names

- Consistent kebab-case string identifiers: `"compute-agent"`, `"network-agent"`, `"arc-agent"`, `"orchestrator"`
- Used as both the agent `name=` field and OpenTelemetry service name prefix (`"aiops-compute-agent"`)

---

## 2. Module / File Organization

### Python Services

Each service follows a **flat module layout** inside its directory:

```
services/api-gateway/
    __init__.py
    main.py          # FastAPI app + route registration
    models.py        # Pydantic request/response models
    auth.py          # Authentication dependency
    chat.py          # Chat endpoint logic
    foundry.py       # Foundry client factory + thread dispatch
    approvals.py     # Approval lifecycle
    audit.py         # Audit log queries
    rate_limiter.py  # Sliding-window rate limiting
    runbook_rag.py   # pgvector RAG search
    patch_endpoints.py  # Patch management routes (Phase 13)
    tests/
        conftest.py
        test_*.py
```

### Agent Package Layout

Each domain agent is a **two-file package**: `agent.py` + `tools.py`:

```
agents/
    orchestrator/
        agent.py     # ChatAgent factory + system prompt
    compute/
        agent.py     # ChatAgent factory + COMPUTE_AGENT_SYSTEM_PROMPT
        tools.py     # @ai_function tool definitions + ALLOWED_MCP_TOOLS
    network/, storage/, security/, sre/, arc/, patch/, eol/
        (same pattern)
    shared/
        auth.py      # DefaultAzureCredential + AgentsClient factory
        envelope.py  # IncidentMessage TypedDict + validate_envelope()
        otel.py      # setup_telemetry() + instrument_tool_call()
        triage.py    # TriageDiagnosis + RemediationProposal + ResourceSnapshot
        budget.py    # BudgetTracker + cost calculation
        routing.py   # classify_query_text() keyword router
        approval_manager.py
        gitops.py
        resource_identity.py
        runbook_tool.py
    tests/
        shared/      # Unit tests for shared/ modules
        integration/ # Integration tests for agent workflows
```

### Arc MCP Server Layout

Implements the **tool-per-domain split** into `tools/` sub-package:

```
services/arc-mcp-server/
    server.py        # FastMCP app + @mcp.tool() registrations
    auth.py          # DefaultAzureCredential helper
    models.py        # Pydantic result models
    tools/
        arc_servers.py   # HybridComputeManagementClient tools
        arc_k8s.py       # ConnectedKubernetesClient tools
        arc_data.py      # AzureArcDataManagementClient tools
```

Tools in `tools/*.py` expose `*_impl()` async functions. The `server.py` registers
them as `@mcp.tool()` wrappers that call `*_impl()` and call `.model_dump()` on the result.

### TypeScript Services

Teams Bot follows **feature-grouped** layout mirroring the Python pattern:

```
services/teams-bot/src/
    index.ts             # Express app entry point
    bot.ts               # Bot activity handler
    config.ts            # Config object (reads env vars)
    types.ts             # Shared TypeScript interfaces
    cards/               # Adaptive Card builders
        approval-card.ts
        alert-card.ts
        outcome-card.ts
        reminder-card.ts
        __tests__/       # Co-located tests
    routes/              # Express route handlers
        health.ts
        notify.ts
        __tests__/
    services/            # Business logic
        auth.ts
        gateway-client.ts
        proactive.ts
        conversation-state.ts
        escalation.ts
        __tests__/
```

Web UI follows Next.js App Router conventions:

```
services/web-ui/
    app/
        api/
            stream/route.ts    # SSE streaming proxy
            proxy/[...path]/route.ts  # Generic API proxy
    lib/
        format-relative-time.ts  # Shared utility (with unit tests)
        __tests__/
    __tests__/                 # Top-level Jest tests
    __mocks__/                 # Manual mocks (next-server.ts)
```

---

## 3. Error Handling Patterns

### Python: Explicit Exception Classes

Custom exceptions are declared at module level with structured attributes:

```python
class BudgetExceededException(Exception):
    def __init__(self, session_id: str, total_cost_usd: float, threshold_usd: float):
        ...

class RateLimitExceededError(Exception): ...
class ProtectedResourceError(Exception): ...
class RunbookSearchUnavailableError(Exception): ...
```

### Python: FastAPI Error Translation

Business exceptions translate to HTTP exceptions at the route boundary — never inside business logic:

```python
# In route handler (main.py):
try:
    result = await create_foundry_thread(payload)
except ValueError as exc:
    raise HTTPException(status_code=503, detail=f"Foundry dispatch unavailable: {exc}") from exc
except Exception as exc:
    raise HTTPException(status_code=500, detail="Internal error dispatching incident") from exc
```

- `ValueError` → 400 or 503 (configuration/validation errors)
- Specific business exceptions → 410 (expired), 403 (scope confirmation)
- Generic `Exception` → 500 (logged with full context)
- Always `raise ... from exc` to preserve exception chains

### Python: Fail-Closed Auth

Auth module defaults to **fail-closed**: missing env vars → 503 with actionable error message.
Bypass is opt-in via `API_GATEWAY_AUTH_MODE=disabled` (test environments only).

### Python: Graceful Degradation for Optional Services

Optional services (Postgres, App Insights, Cosmos) guard with try/except at startup:

```python
except Exception as exc:  # noqa: BLE001
    logger.warning("Startup migrations skipped: %s", exc)
```

Missing env vars → logged as warnings, feature silently skipped (not a fatal error).

### TypeScript: try/catch with unknown narrowing

```typescript
} catch (error: unknown) {
    logger.error('Operation failed', error)
    throw new Error(getErrorMessage(error))
}
```

---

## 4. Logging Patterns

### Python

- **Module-level logger** using the standard library: `logger = logging.getLogger(__name__)`
- **Structured log calls** with format string arguments (not f-strings):
  `logger.info("Ingesting incident %s (severity=%s)", payload.incident_id, payload.severity)`
- **Error log with full context** before raising: `logger.error("Foundry dispatch failed: %s", exc)`
- **Warning for degraded paths**: `logger.warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set — OTel disabled")`
- No `print()` statements in production code
- Log level configurable via `LOG_LEVEL` env var (default `INFO`)

### OpenTelemetry Spans (Production Observability)

All agent tool calls are wrapped with `instrument_tool_call()` from `agents/shared/otel.py`:

```python
tracer = setup_telemetry("aiops-compute-agent")   # module-level

with instrument_tool_call(
    tracer=tracer,
    agent_name="compute-agent",
    agent_id=agent_id,
    tool_name="query_activity_log",
    tool_parameters=tool_params,
    correlation_id="",
    thread_id="",
):
    ...
```

Gateway-layer spans use purpose-specific helpers from `services/api-gateway/instrumentation.py`:

```python
with foundry_span("create_thread") as span:
    span.set_attribute("foundry.thread_id", thread_id)

with agent_span("orchestrator", correlation_id="..."):
    ...

with mcp_span("tool_approval", thread_id=thread_id) as span:
    span.set_attribute("mcp.tool_calls_count", str(len(tool_outputs)))
```

All spans flow to Azure Application Insights via `APPLICATIONINSIGHTS_CONNECTION_STRING`.

---

## 5. API Patterns

### Route Registration

- `main.py` is the FastAPI app + route registration hub
- Sub-routers (`health_router`, `patch_router`) registered via `app.include_router()`
- All routes use Pydantic `response_model=` for automatic serialization and schema generation
- Non-idempotent creation routes return `status.HTTP_202_ACCEPTED`

### Middleware Stack (applied in order)

1. **CORS** — origins from `CORS_ALLOWED_ORIGINS` env var (comma-separated; default `*` for dev)
2. **Correlation ID** — injects `X-Correlation-ID` header on every request/response (generates UUID if absent)
3. **HTTP Rate Limiter** — per-IP sliding window on `/api/v1/chat` (POST) and `/api/v1/incidents` (GET)

### Authentication Dependency

All protected routes declare `token: dict[str, Any] = Depends(verify_token)`.
The `verify_token` dependency returns the decoded Entra token claims dict.
Auth mode controlled by `API_GATEWAY_AUTH_MODE` env var (`"entra"` | `"disabled"`).

### Pydantic Model Pattern

All request/response models inherit from `pydantic.BaseModel` with field-level validation:

```python
class IncidentPayload(BaseModel):
    incident_id: str = Field(..., min_length=1)
    severity: str = Field(..., pattern=r"^Sev[0-3]$")
    domain: str = Field(..., pattern=r"^(compute|network|storage|security|arc|sre|patch|eol)$")
    affected_resources: list[AffectedResource] = Field(..., min_length=1)
    kql_evidence: Optional[str] = Field(default=None, description="...")
```

All models live in `models.py` — never inline in route handlers.

### Envelope Protocol

Agent-to-agent messages use the `IncidentMessage` TypedDict from `agents/shared/envelope.py`:

```python
class IncidentMessage(TypedDict):
    correlation_id: str
    thread_id: str
    source_agent: str
    target_agent: str
    message_type: Literal["incident_handoff", "diagnosis_complete", "remediation_proposal", ...]
    payload: dict[str, Any]
    timestamp: str  # ISO 8601
```

Raw strings between agents are prohibited (AGENT-002). Every inbound message validated
with `validate_envelope()` before processing.

---

## 6. Component Patterns (Frontend)

### Next.js App Router

- API proxy routes in `app/api/proxy/[...path]/route.ts` — forwards all methods to the backend API gateway
- SSE streaming route in `app/api/stream/route.ts` — polls backend, re-emits as SSE with 20s heartbeat
- `ReadableStream` + `TransformStream` used directly (no Vercel AI SDK dependency)
- Server components only where no client-side state is required; `"use client"` directive explicit

### SSE Streaming Pattern

```typescript
// app/api/stream/route.ts
const stream = new ReadableStream({
  start(controller) {
    // Poll backend GET /chat/{thread_id}/result every 2s
    // Emit "data: <json>\n\n" on each result
    // Emit ": heartbeat\n\n" every 20s via setInterval
    // Close stream on terminal run_status (completed/failed/cancelled/expired)
  }
});
return new Response(stream, {
  headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" }
});
```

### Shared Utilities

- `lib/format-relative-time.ts` — pure function, independently unit-tested with Jest
- All lib utilities are pure functions with no side effects (easily testable)

### Fluent UI v9 + Tailwind

- Uses `@fluentui/react-components` v9 (not legacy v8)
- Tailwind used for layout; Fluent UI for interactive components
- `FluentProvider` wraps the entire app in the root layout

---

## 7. Git Conventions (from recent commits)

### Commit Message Format

```
<type>(<scope>): <description>
```

**Types observed:**
- `feat` — new feature (`feat: resizable chat drawer + table overflow fix`)
- `fix` — bug fix (`fix: use REST API directly for sub-run thread listing (fast path)`)
- `docs` — documentation/verification (`docs(13): verify phase 13 — all must_haves pass`)
- `chore` — housekeeping (`chore: update STATE.md with quick task 260401-ata`)
- `refactor` — code restructuring

**Scope convention:** Phase number in parentheses for phase-scoped commits: `docs(13):`, `feat(12):`.

**Description style:** Imperative present tense, concise summary of the what and why.
Multi-fix commits use `+` to separate concerns in a single line.

### Branch Strategy

- Main branch: `main` — deployable at all times
- Feature branches created per task/phase: convention observed from GSD workflow
- PRs merge to `main` after CI passes; no long-lived feature branches

---

## 8. Environment Variable Conventions

### Naming Pattern

All env vars are `UPPER_SNAKE_CASE`. Azure SDK env vars use the official names:

| Variable | Where Used | Purpose |
|---|---|---|
| `AZURE_PROJECT_ENDPOINT` | `agents/shared/auth.py`, `foundry.py` | Foundry project endpoint (preferred) |
| `FOUNDRY_ACCOUNT_ENDPOINT` | Same | Fallback Foundry endpoint |
| `AZURE_CLIENT_ID` | `services/api-gateway/auth.py` | Entra app client ID |
| `AZURE_TENANT_ID` | `services/api-gateway/auth.py` | Entra tenant ID |
| `AGENT_ENTRA_ID` | `agents/shared/auth.py` | Agent managed identity principal_id |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | `agents/shared/otel.py`, `main.py` | App Insights OTel |
| `COSMOS_ENDPOINT` | `agents/shared/budget.py`, detection-plane | Cosmos DB account endpoint |
| `COSMOS_DATABASE_NAME` | Same | Cosmos DB database |
| `ORCHESTRATOR_AGENT_ID` | `services/api-gateway/chat.py`, `foundry.py` | Foundry assistant ID |
| `API_GATEWAY_AUTH_MODE` | `services/api-gateway/auth.py` | `"entra"` (default) or `"disabled"` |
| `CORS_ALLOWED_ORIGINS` | `services/api-gateway/main.py` | Comma-separated CORS origins |
| `MAX_ACTIONS_PER_MINUTE` | `services/api-gateway/rate_limiter.py` | Remediation rate limit |
| `BUDGET_THRESHOLD_USD` | `agents/shared/budget.py` | Per-session cost ceiling |
| `MAX_ITERATIONS` | `agents/shared/budget.py` | Per-session iteration cap |
| `LOG_LEVEL` | `services/api-gateway/main.py` | Log verbosity (default `INFO`) |

### Env Var Access Pattern

- **Required vars:** explicit `ValueError` with actionable message:
  ```python
  endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT")
  if not endpoint:
      raise ValueError("AZURE_PROJECT_ENDPOINT ... is required. Set by the agent-apps Terraform module.")
  ```
- **Optional vars with defaults:** `os.environ.get("VAR", default_value)`
- **Feature flags:** `os.environ.get("FEATURE", "").lower() == "enabled"` pattern

---

## 9. Import / Dependency Patterns

### Python Import Order (PEP 8 + isort)

1. `from __future__ import annotations` (always first, in all modules)
2. Standard library (`os`, `logging`, `uuid`, `time`, etc.)
3. Third-party (`fastapi`, `pydantic`, `azure.*`, `mcp`, `agent_framework`)
4. Local relative (`from agents.shared.auth import ...`, `from services.api_gateway.models import ...`)

### Lazy Imports for Optional Dependencies

Optional dependencies imported inside functions to avoid startup errors:

```python
# Inside route handler:
from services.api_gateway.dedup_integration import check_dedup   # deferred
import asyncpg                                                      # inside lifespan
from azure.monitor.opentelemetry import configure_azure_monitor   # only if env var set
```

### Shared Utilities Import

All agents import from `agents.shared.*`:
```python
from agents.shared.auth import get_foundry_client, get_agent_identity
from agents.shared.otel import setup_telemetry, instrument_tool_call
from agents.shared.envelope import validate_envelope, IncidentMessage
from agents.shared.triage import TriageDiagnosis, RemediationProposal
```

---

## 10. Code Documentation Style

### Module Docstrings

Every module has a docstring with:
- One-line summary
- List of endpoints / tools / responsibilities
- Requirement references in parentheses: `(TRIAGE-002, REMEDI-001, AGENT-008)`

### Function/Method Docstrings (Google style)

```python
def setup_telemetry(service_name: str) -> trace.Tracer:
    """Configure OpenTelemetry for an agent container.

    Args:
        service_name: Agent service name (e.g., "aiops-compute-agent").

    Returns:
        An OpenTelemetry Tracer for the given service.
    """
```

- Args block for non-trivial parameters
- Returns block describes return type and structure
- Raises block for functions that raise specific exceptions
- Inline requirement reference: `# REMEDI-001: All remediation proposals require explicit human approval.`

### Section Separators

Long modules use dashed comment separators for logical sections:

```python
# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------
```
