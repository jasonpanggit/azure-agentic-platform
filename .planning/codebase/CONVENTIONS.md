# Code Conventions — Azure Agentic Platform

> Extracted from codebase inspection. Last updated: 2026-03-30.

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
underscore-namespaced Python packages (`services.api_gateway`) in `conftest.py`.

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
    network/, storage/, security/, sre/, arc/
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
them as `@mcp.tool()` wrappers that call `*_impl()` and call `.model_dump()` on
the result.

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

Auth module defaults to **fail-closed**: missing env vars → 503 with actionable error message. Bypass is opt-in (`API_GATEWAY_AUTH_MODE=disabled`).

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
- **Structured log calls** with format string arguments (not f-strings): `logger.info("Ingesting incident %s (severity=%s)", payload.incident_id, payload.severity)`
- **Error log with full context** before raising: `logger.error("Foundry dispatch failed: %s", exc)`
- **Warning for degraded paths**: `logger.warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set — OTel disabled")`
- No `print()` statements in production code

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

The context manager automatically records:
- `aiops.agent_id`, `aiops.agent_name`, `aiops.tool_name`
- `aiops.tool_parameters`, `aiops.correlation_id`, `aiops.thread_id`
- `aiops.outcome` (`success` | `failure`)
- `aiops.duration_ms` (wall-clock)
- `aiops.error` (exception string on failure)

All spans flow to Azure Application Insights via `APPLICATIONINSIGHTS_CONNECTION_STRING`.

---

## 5. Environment Variable Conventions

### Naming Pattern

All env vars are `UPPER_SNAKE_CASE`. Azure SDK env vars use the official names:

| Variable | Where Used | Purpose |
|---|---|---|
| `AZURE_PROJECT_ENDPOINT` | `agents/shared/auth.py`, `services/api-gateway/foundry.py` | Foundry project endpoint (preferred) |
| `FOUNDRY_ACCOUNT_ENDPOINT` | Same | Fallback Foundry endpoint |
| `AZURE_CLIENT_ID` | `services/api-gateway/auth.py` | Entra app client ID |
| `AZURE_TENANT_ID` | `services/api-gateway/auth.py` | Entra tenant ID |
| `AGENT_ENTRA_ID` | `agents/shared/auth.py` | Agent's managed identity principal_id for audit |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | `agents/shared/otel.py`, `services/api-gateway/main.py` | App Insights OTel |
| `COSMOS_ENDPOINT` | `agents/shared/budget.py`, detection-plane | Cosmos DB account endpoint |
| `COSMOS_DATABASE_NAME` | Same | Cosmos DB database |
| `ORCHESTRATOR_AGENT_ID` | `services/api-gateway/chat.py`, `foundry.py` | Foundry assistant ID for runs |
| `API_GATEWAY_AUTH_MODE` | `services/api-gateway/auth.py` | `"entra"` (default) or `"disabled"` |
| `CORS_ALLOWED_ORIGINS` | `services/api-gateway/main.py` | Comma-separated CORS origins |
| `MAX_ACTIONS_PER_MINUTE` | `services/api-gateway/rate_limiter.py` | Remediation rate limit |
| `BUDGET_THRESHOLD_USD` | `agents/shared/budget.py` | Per-session cost ceiling |
| `MAX_ITERATIONS` | `agents/shared/budget.py` | Per-session iteration cap |
| `INPUT_PRICE_PER_1M` / `OUTPUT_PRICE_PER_1M` | `agents/shared/budget.py` | Token pricing for cost calc |

### Env Var Access Pattern

- **Required vars:** `os.environ["VAR"]` (raises `KeyError`) or explicit `ValueError` with actionable message:
  ```python
  endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT")
  if not endpoint:
      raise ValueError("AZURE_PROJECT_ENDPOINT ... is required. Set by the agent-apps Terraform module.")
  ```
- **Optional vars with defaults:** `os.environ.get("VAR", default_value)`
- **Feature flags:** `os.environ.get("FEATURE", "").lower() == "enabled"` pattern

---

## 6. Import / Dependency Patterns

### Python Import Order (PEP 8 + isort)

1. `from __future__ import annotations` (always first, in all modules)
2. Standard library (`os`, `logging`, `uuid`, `time`, etc.)
3. Third-party (`fastapi`, `pydantic`, `azure.*`, `mcp`, `agent_framework`)
4. Local relative (`from agents.shared.auth import ...`, `from services.api_gateway.models import ...`)

### Lazy Imports for Optional Dependencies

Optional dependencies imported inside functions to avoid startup errors:

```python
# In main.py startup:
from services.api_gateway.dedup_integration import check_dedup   # inside route handler
import asyncpg                                                      # inside lifespan
from azure.monitor.opentelemetry import configure_azure_monitor   # if env var set
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

## 7. Agent Framework Patterns

### Agent Declaration (`agent.py`)

Each domain agent follows the same factory function pattern:

```python
# 1. Module docstring with requirement references (TRIAGE-002, REMEDI-001, etc.)
# 2. Import ChatAgent from agent_framework
# 3. Import tools from sibling tools.py
# 4. Module-level tracer: tracer = setup_telemetry("aiops-<domain>-agent")
# 5. Module-level SYSTEM_PROMPT constant with {allowed_tools} placeholder
# 6. Factory function create_<domain>_agent() -> ChatAgent
# 7. __main__ entry point: agent.serve()

def create_compute_agent() -> ChatAgent:
    client = get_foundry_client()
    return ChatAgent(
        name="compute-agent",
        description="Azure compute domain specialist — VMs, VMSS, AKS, App Service.",
        system_prompt=COMPUTE_AGENT_SYSTEM_PROMPT,
        client=client,
        tools=[query_activity_log, query_log_analytics, query_resource_health, query_monitor_metrics],
    )

if __name__ == "__main__":
    agent = create_compute_agent()
    agent.serve()
```

### Tool Declaration (`tools.py`)

All agent tools use the `@ai_function` decorator from `agent_framework`:

```python
@ai_function
def query_activity_log(
    resource_ids: List[str],
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Docstring with Args: and Returns: sections.

    MANDATORY first-pass RCA step (TRIAGE-003). ...
    """
    agent_id = get_agent_identity()
    tool_params = {...}
    with instrument_tool_call(tracer, "compute-agent", agent_id, "query_activity_log", tool_params, ...):
        return {...}   # Typed dict result
```

**Rules:**
- Every `@ai_function` is wrapped with `instrument_tool_call` for OTel tracing
- Return values are plain `Dict[str, Any]` with consistent key naming
- Every tools module declares an explicit `ALLOWED_MCP_TOOLS: List[str]` allowlist — no wildcards

### MCP Tool Declaration (Arc MCP Server)

```python
@mcp.tool()
async def arc_servers_list(subscription_id: str, resource_group: Optional[str] = None) -> dict:
    """Docstring with Args: and Returns: sections."""
    result = await arc_servers_list_impl(subscription_id, resource_group)
    return result.model_dump()
```

- Registration thin wrappers in `server.py` delegate to `*_impl()` async functions in `tools/`
- Return type always `dict` (from `.model_dump()` on a Pydantic model)

### Inter-Agent Message Protocol

All agent-to-agent messages use the `IncidentMessage` TypedDict from `agents/shared/envelope.py`:

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

Raw strings between agents are prohibited (AGENT-002). Every message is validated
with `validate_envelope()` before processing.

---

## 8. Common Utilities and Shared Code

### `agents/shared/`

| Module | Purpose |
|---|---|
| `auth.py` | `get_credential()`, `get_foundry_client()`, `get_agent_identity()` — cached via `@lru_cache` |
| `envelope.py` | `IncidentMessage` TypedDict, `VALID_MESSAGE_TYPES`, `validate_envelope()` |
| `otel.py` | `setup_telemetry()`, `instrument_tool_call()` context manager, `record_tool_call_span()` |
| `triage.py` | `TriageDiagnosis`, `RemediationProposal`, `ResourceSnapshot` — typed domain result containers |
| `budget.py` | `BudgetTracker`, `calculate_cost()`, `BudgetExceededException`, `MaxIterationsExceededException` |
| `routing.py` | `classify_query_text()` — keyword-based domain classifier for operator chat messages |
| `approval_manager.py` | HITL approval lifecycle utilities |
| `gitops.py` | GitOps path execution helpers |
| `resource_identity.py` | Resource Identity Certainty (REMEDI-004) snapshot + verification |
| `runbook_tool.py` | Shared `@ai_function` for runbook RAG search |

### `services/api-gateway/` Business Modules

| Module | Purpose |
|---|---|
| `models.py` | All Pydantic request/response models (`IncidentPayload`, `ChatRequest`, `ApprovalRecord`, etc.) |
| `auth.py` | `EntraTokenValidator` class + `verify_token()` FastAPI dependency |
| `foundry.py` | `_get_foundry_client()` (thread/message/run operations) |
| `rate_limiter.py` | `RateLimiter` sliding window, `check_protected_tag()`, singleton `rate_limiter` |
| `audit_trail.py` | Audit trail write path (Cosmos DB) |
| `audit.py` | Audit log read/query path (Application Insights) |
| `dedup_integration.py` | `check_dedup()` — incident deduplication against Cosmos |

### Pydantic Models Pattern

All API request/response models inherit from `pydantic.BaseModel` with field-level validation:

```python
class IncidentPayload(BaseModel):
    incident_id: str = Field(..., min_length=1)
    severity: str = Field(..., pattern=r"^Sev[0-3]$")
    domain: str = Field(..., pattern=r"^(compute|network|storage|security|arc|sre)$")
    affected_resources: list[AffectedResource] = Field(..., min_length=1)
```

### Singleton Pattern

Module-level singletons for shared service clients:
- `rate_limiter = RateLimiter()` in `rate_limiter.py`
- `_token_validator = EntraTokenValidator()` in `auth.py`
- `@lru_cache(maxsize=1)` on `get_credential()` for thread-safe caching

---

## 9. Code Documentation Style

### Module Docstrings

Every module has a docstring with:
- One-line summary
- List of endpoints / tools / responsibilities
- Requirement references in parentheses: `(TRIAGE-002, REMEDI-001, AGENT-008)`

### Function/Method Docstrings (Google style)

```python
def setup_telemetry(service_name: str) -> trace.Tracer:
    """Configure OpenTelemetry for an agent container.

    Reads APPLICATIONINSIGHTS_CONNECTION_STRING from environment.
    Returns a Tracer instance for creating custom spans.

    Args:
        service_name: Agent service name (e.g., "aiops-compute-agent").

    Returns:
        An OpenTelemetry Tracer for the given service.
    """
```

- Args block always present for non-trivial parameters
- Returns block describes the return type and structure
- Raises block for functions that raise specific exceptions
- Inline requirement reference for constraint-carrying code: `# REMEDI-001: All remediation proposals require explicit human approval.`

### Section Separators

Long modules use dashed comment separators for logical sections:

```python
# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------
```
