---
phase: 02-agent-core
plan: "02-03"
subsystem: api
tags: [fastapi, pydantic, entra-id, azure-ai-projects, docker, python, jwt]

# Dependency graph
requires:
  - phase: 02-01
    provides: Container Apps environment, Terraform agent-apps module, API gateway Container App provisioned
provides:
  - FastAPI incident ingestion service at services/api-gateway/
  - POST /api/v1/incidents — accepts IncidentPayload, creates Foundry thread, returns 202
  - GET /health — unauthenticated health check returning {"status":"ok","version":"1.0.0"}
  - Entra ID Bearer token validation via fastapi-azure-auth (dev-mode fallback when AZURE_CLIENT_ID unset)
  - Foundry thread dispatch — typed incident_handoff envelope (AGENT-002), AIProjectClient create_thread + create_message + create_run
  - Dockerfile (python:3.12-slim, non-root gatewayuser, port 8000, uvicorn)
  - CI workflow api-gateway-build.yml delegating to reusable docker-push.yml
  - 9 passing unit tests (health + payload validation + dispatch mocking)
  - conftest.py package shim registering services/api-gateway as services.api_gateway

affects:
  - phase-04-detection-plane  # Fabric Activator POSTs to this endpoint
  - phase-05-triage-remediation  # SSE streaming builds on incident ingestion

# Tech tracking
tech-stack:
  added:
    - fastapi>=0.115.0
    - uvicorn[standard]>=0.30.0
    - pydantic>=2.8.0
    - azure-identity>=1.17.0
    - fastapi-azure-auth>=5.0.0
    - azure-ai-projects>=2.0.1
  patterns:
    - Thin routing layer — no business logic in gateway; agents own reasoning
    - Dev-mode auth fallback — AZURE_CLIENT_ID absent disables validation with warning
    - Typed envelope pattern (AGENT-002) — all agent-to-agent messages use correlation_id + typed message_type
    - Correlation ID middleware — X-Correlation-ID injected into every request/response
    - conftest.py hyphenated package shim — maps services/api-gateway → services.api_gateway for Python imports

key-files:
  created:
    - services/api-gateway/__init__.py
    - services/api-gateway/models.py
    - services/api-gateway/auth.py
    - services/api-gateway/foundry.py
    - services/api-gateway/main.py
    - services/api-gateway/Dockerfile
    - services/api-gateway/requirements.txt
    - services/api-gateway/tests/__init__.py
    - services/api-gateway/tests/test_health.py
    - services/api-gateway/tests/test_incidents.py
    - .github/workflows/api-gateway-build.yml
    - conftest.py
    - services/__init__.py
  modified:
    - pyproject.toml (added pythonpath=["."] for pytest)

key-decisions:
  - "Dev-mode auth fallback: AZURE_CLIENT_ID absent → validator is None → all requests allowed with warning (not error) for local dev ergonomics"
  - "Optional[X] instead of X | None in function signatures for Python 3.9 compat (FastAPI evaluates annotations at runtime via get_type_hints)"
  - "conftest.py package shim + setattr on parent module required for unittest.mock.patch to resolve services.api_gateway via getattr()"
  - "Gateway is thin routing only — no business logic, no domain reasoning; all incident processing happens in Foundry agent threads"
  - "AZURE_PROJECT_ENDPOINT and ORCHESTRATOR_AGENT_ID read from env at call time — not at module import — enabling easy test mocking"

patterns-established:
  - "Pattern 1: Typed envelope — all agent-to-agent messages: {correlation_id, thread_id, source_agent, target_agent, message_type, payload, timestamp}"
  - "Pattern 2: Dev-mode fallback — auth/external deps disabled gracefully when env vars absent, with explicit WARNING log"
  - "Pattern 3: conftest.py shim — register hyphenated directories as Python packages + setattr on parent for mock.patch compatibility"
  - "Pattern 4: 202 Accepted for async dispatch — incident endpoint returns immediately with thread_id; agent processing is async"

requirements-completed: [DETECT-004, MONITOR-001, MONITOR-002, MONITOR-003]

# Metrics
duration: 35min
completed: 2026-03-26
---

# Plan 02-03: API Gateway — Incident Endpoint Summary

**FastAPI incident gateway at services/api-gateway/ — POST /api/v1/incidents with Entra Bearer token validation, typed Foundry thread dispatch, Dockerfile, CI workflow, and 9 passing tests**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-03-26T00:00:00Z
- **Completed:** 2026-03-26T00:35:00Z
- **Tasks:** 7 (03.01–03.07) + 1 fix commit
- **Files created:** 13

## Accomplishments

- `POST /api/v1/incidents` validates IncidentPayload (severity Sev0-Sev3, domain enum, min 1 affected_resource), creates a Foundry thread with typed envelope, returns 202 with thread_id
- Entra ID auth via `SingleTenantAzureAuthorizationCodeBearer` — reads AZURE_CLIENT_ID/AZURE_TENANT_ID from env, graceful dev-mode fallback when unset
- Foundry dispatch posts `incident_handoff` typed envelope (AGENT-002) and starts Orchestrator run via AIProjectClient
- All 9 unit tests pass: health (3), payload validation (4), dispatch mocking (2)

## Task Commits

1. **Task 03.01: Pydantic models** — `b1ad3a4` (feat)
2. **Task 03.02: Entra auth middleware** — `ff3afab` (feat)
3. **Task 03.03: Foundry thread dispatch** — `0057051` (feat)
4. **Task 03.04: FastAPI main app** — `6c2c236` (feat)
5. **Task 03.05: Dockerfile + requirements** — `040aa2a` (feat)
6. **Task 03.06: CI workflow** — `9d2ee47` (ci)
7. **Task 03.07: Unit tests** — `ffe7390` (test)
8. **Fix: Python 3.9 compat + conftest shim** — `b5e1cd2` (fix)

## Files Created/Modified

- `services/api-gateway/__init__.py` — empty package init
- `services/api-gateway/models.py` — IncidentPayload, AffectedResource, IncidentResponse, HealthResponse (DETECT-004)
- `services/api-gateway/auth.py` — Entra token validator with SingleTenantAzureAuthorizationCodeBearer and dev-mode fallback
- `services/api-gateway/foundry.py` — AIProjectClient thread/message/run creation with typed AGENT-002 envelope
- `services/api-gateway/main.py` — FastAPI app with POST /api/v1/incidents (202) and GET /health, CORSMiddleware, X-Correlation-ID
- `services/api-gateway/Dockerfile` — python:3.12-slim, non-root gatewayuser, port 8000, uvicorn CMD
- `services/api-gateway/requirements.txt` — fastapi, uvicorn, pydantic, azure-identity, fastapi-azure-auth, azure-ai-projects
- `services/api-gateway/tests/test_health.py` — 3 health endpoint tests
- `services/api-gateway/tests/test_incidents.py` — 4 validation tests + 2 dispatch mock tests
- `.github/workflows/api-gateway-build.yml` — triggers on services/api-gateway/**, delegates to docker-push.yml
- `conftest.py` — hyphenated package shim (api-gateway → api_gateway) with setattr for mock.patch compat
- `services/__init__.py` — services namespace package
- `pyproject.toml` — added pythonpath=["."]

## Decisions Made

- **Dev-mode auth fallback**: When `AZURE_CLIENT_ID` is absent, validator is `None` and all requests pass with a WARNING log. Allows local development without Entra credentials.
- **`Optional[X]` in signatures**: FastAPI's `get_type_hints()` evaluates annotations at runtime; `X | None` union syntax fails on Python 3.9. Using `Optional[X]` from `typing` resolves this while keeping `from __future__ import annotations` for other uses.
- **conftest.py shim**: Python cannot import directories with hyphens. The shim registers `services/api-gateway` as `sys.modules["services.api_gateway"]` and also calls `setattr(services_module, "api_gateway", mod)` so that `unittest.mock.patch("services.api_gateway.main.create_foundry_thread")` resolves correctly via `_importer`.
- **Gateway as thin router**: No business logic in the gateway. The Pydantic layer validates, Foundry layer dispatches, and all reasoning is deferred to agent threads. Keeps the gateway small and testable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Python 3.9 compat] Union type annotation syntax incompatible with FastAPI's runtime type evaluation**
- **Found during:** Task 03.07 (running tests)
- **Issue:** `X | None` in function signatures fails at FastAPI startup on Python 3.9 even with `from __future__ import annotations`, because `fastapi.dependencies.utils.get_typed_signature()` calls `get_type_hints()` which evaluates the annotations at runtime
- **Fix:** Replaced `X | None` with `Optional[X]` in `auth.py` function signatures (both `validate()` and `verify_token()`)
- **Files modified:** `services/api-gateway/auth.py`
- **Verification:** `python3 -m pytest services/api-gateway/tests/ -v` — 9/9 passing
- **Committed in:** `b5e1cd2` (fix commit after task 03.07)

**2. [Import path] `services/api-gateway` directory cannot be imported as `services.api_gateway`**
- **Found during:** Task 03.07 (test collection)
- **Issue:** Python cannot import directories containing hyphens; `from services.api_gateway.main import app` fails with `ModuleNotFoundError`
- **Fix:** Added `conftest.py` with `_register_hyphenated_package()` that creates a synthetic module in `sys.modules` pointing to the hyphenated directory; added `setattr(parent, leaf, mod)` to fix `unittest.mock.patch` resolution; added `services/__init__.py` and `pythonpath=["."]` to `pyproject.toml`
- **Files modified:** `conftest.py` (new), `services/__init__.py` (new), `pyproject.toml`
- **Verification:** 9/9 tests pass including mock.patch-based dispatch tests
- **Committed in:** `b5e1cd2`

---

**Total deviations:** 2 auto-fixed (1 Python version compat, 1 import path)
**Impact on plan:** Both fixes necessary for correctness. No scope creep. The conftest.py shim is reusable for future services with hyphenated directories.

## Issues Encountered

- System Python is 3.9.6 but pyproject.toml requires `>=3.10`; the `|` union syntax issues only manifest at runtime, not import time with `from __future__ import annotations`. Fixed by using `Optional[]` in FastAPI-inspected signatures.
- `unittest.mock.patch` uses `_importer` which calls `getattr(parent_module, leaf_name)` — not just `sys.modules` lookup — requiring the extra `setattr` call in `conftest.py`.

## User Setup Required

The following environment variables must be set for production use:

| Variable | Required | Purpose |
|---|---|---|
| `AZURE_CLIENT_ID` | Production only | App registration client ID for Entra token validation |
| `AZURE_TENANT_ID` | Production only | Entra tenant ID |
| `AZURE_PROJECT_ENDPOINT` | Required | Foundry project endpoint for AIProjectClient |
| `ORCHESTRATOR_AGENT_ID` | Required | Foundry agent ID of the Orchestrator agent |

In development (no `AZURE_CLIENT_ID`), auth is disabled with a warning and all requests pass.

## Next Phase Readiness

- `POST /api/v1/incidents` endpoint is ready to receive triggers from Phase 4 (Fabric Activator)
- Foundry thread dispatch will be fully functional once `AZURE_PROJECT_ENDPOINT` and `ORCHESTRATOR_AGENT_ID` are set (Phase 2 agent deployment)
- 9/9 unit tests passing; CI workflow ready to build/push on merge to main

---
*Phase: 02-agent-core*
*Completed: 2026-03-26*
