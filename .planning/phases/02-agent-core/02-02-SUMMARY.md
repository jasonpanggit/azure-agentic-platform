---
plan: "02-02"
phase: 2
title: "Shared Agent Infrastructure"
status: complete
completed_at: "2026-03-26"
---

# Plan 02-02 Summary: Shared Agent Infrastructure

## What Was Built

This plan delivered the shared Python foundation that all 7 AAP domain agents depend on. Seven tasks were executed and committed atomically.

## Tasks Completed

### Task 02.01 — Typed Message Envelope
- Created `agents/shared/__init__.py` (package init)
- Created `agents/shared/envelope.py` with `IncidentMessage` TypedDict (7 fields: `correlation_id`, `thread_id`, `source_agent`, `target_agent`, `message_type`, `payload`, `timestamp`)
- 5 valid message type literals enforced via `VALID_MESSAGE_TYPES` frozenset
- `validate_envelope()` function with full field/type/value validation
- **Satisfies:** AGENT-002

### Task 02.02 — OpenTelemetry Instrumentation
- Created `agents/shared/otel.py` with:
  - `setup_telemetry(service_name)` → reads `APPLICATIONINSIGHTS_CONNECTION_STRING`, calls `configure_azure_monitor()`, returns `Tracer`
  - `record_tool_call_span()` → post-hoc span creation with all 8 AUDIT-001 attributes: `aiops.agent_id`, `aiops.agent_name`, `aiops.tool_name`, `aiops.tool_parameters`, `aiops.outcome`, `aiops.duration_ms`, `aiops.correlation_id`, `aiops.thread_id`
  - `instrument_tool_call()` → context manager for live instrumentation with auto-captured duration, exception recording
- **Satisfies:** MONITOR-007, AUDIT-001, AUDIT-005

### Task 02.03 — DefaultAzureCredential Auth Helper
- Created `agents/shared/auth.py` with:
  - `get_credential()` → cached `DefaultAzureCredential` (resolves managed identity via IMDS in Container Apps)
  - `get_foundry_client()` → `AIProjectClient` from `AZURE_PROJECT_ENDPOINT` env var
  - `get_agent_identity()` → Entra object ID from `AGENT_ENTRA_ID` env var for AUDIT-005 attribution
- No hardcoded secrets anywhere; all credentials from environment
- **Satisfies:** AGENT-008

### Task 02.04 — Session Budget Tracker
- Created `agents/shared/budget.py` with:
  - `BudgetExceededException` and `MaxIterationsExceededException` custom exceptions
  - `calculate_cost()` — USD cost from token counts (configurable pricing via env)
  - `BudgetTracker` class — per-session Cosmos DB tracking with ETag optimistic concurrency
  - `create_session()` → creates Cosmos record with `status: "active"`
  - `check_and_record()` → accumulates tokens/cost, aborts with `status: "aborted"` when limits exceeded
  - `complete_session()` → marks `status: "completed"`
  - Default threshold: $5.00, default max iterations: 10
- **Satisfies:** AGENT-007

### Task 02.05 — Shared Base Docker Image
- Created `agents/requirements-base.txt` with pinned versions:
  - `agent-framework==1.0.0rc5`, `azure-ai-projects>=2.0.1`, `azure-ai-agentserver-core`, `azure-ai-agentserver-agentframework`, `azure-identity>=1.17.0`, `azure-cosmos>=4.7.0`, `azure-monitor-opentelemetry>=1.6.0`, `mcp[cli]>=1.26.0`, `pydantic>=2.8.0`
- Created `agents/Dockerfile.base` — multi-stage `python:3.12-slim`, non-root `agentuser`, `EXPOSE 8088`
- **Satisfies:** AGENT-003 (base for domain agents)

### Task 02.06 — Base Image CI Workflow
- Created `.github/workflows/base-image.yml` triggering on pushes to `main` that touch `agents/Dockerfile.base`, `agents/requirements-base.txt`, or `agents/shared/**`
- Calls reusable `.github/workflows/docker-push.yml` with `image_name: agents/base`, `dockerfile_path: agents/Dockerfile.base`, `build_context: agents/`
- **Satisfies:** CI automation for base image rebuilds

### Task 02.07 — Wave 0 Test Stubs and pyproject.toml
- Created `pyproject.toml` at repo root with pytest configuration (`testpaths`, markers, `pythonpath=["."]`)
- Created test package `__init__.py` files: `agents/tests/`, `agents/tests/shared/`, `agents/tests/integration/`
- Created `agents/tests/shared/test_envelope.py` — 18 unit tests for `IncidentMessage` and `validate_envelope()`
- Created `agents/tests/shared/test_budget.py` — 10 unit tests for `BudgetTracker`, `calculate_cost()`, defaults
- Created integration test stubs (Wave 4, all skipped): `test_handoff.py`, `test_mcp_tools.py`, `test_triage.py`, `test_remediation.py`
- **Satisfies:** Wave 0 test foundation

## Verification Results

```
======================== 28 passed, 1 warning in 0.92s =========================
```
- All 28 unit tests pass (envelope: 18 tests, budget: 10 tests)
- 39 total tests collected (including 11 integration stubs) — 0 import errors
- `agents/shared/` has exactly 5 files: `__init__.py`, `envelope.py`, `otel.py`, `auth.py`, `budget.py`

## Commits

| Commit | Task | Description |
|---|---|---|
| `55a241b` | 02.01 | feat(agents): add shared package init and typed IncidentMessage envelope |
| `8989d38` | 02.02 | feat(agents): add OpenTelemetry instrumentation module with AUDIT-001 span attributes |
| `2ee9a41` | 02.03 | feat(agents): add DefaultAzureCredential auth helper |
| `ccf7251` | 02.04 | feat(agents): add session budget tracker with Cosmos DB ETag concurrency control |
| `0516785` | 02.05 | feat(agents): add shared base Dockerfile and pinned requirements |
| `b5a312b` | 02.06 | feat(ci): add base-image.yml workflow |
| `edc8a11` | 02.07 | feat(tests): add pyproject.toml, Wave 0 unit tests, integration stubs |
| `4250afb` | fix | chore: add pythonpath=["."] to pyproject.toml for pytest module resolution |

## Files Created

```
agents/
├── Dockerfile.base
├── requirements-base.txt
├── shared/
│   ├── __init__.py
│   ├── envelope.py          # IncidentMessage TypedDict + validate_envelope()
│   ├── otel.py              # setup_telemetry(), record_tool_call_span(), instrument_tool_call()
│   ├── auth.py              # get_credential(), get_foundry_client(), get_agent_identity()
│   └── budget.py            # BudgetTracker, BudgetExceededException, calculate_cost()
└── tests/
    ├── __init__.py
    ├── shared/
    │   ├── __init__.py
    │   ├── test_envelope.py  # 18 unit tests
    │   └── test_budget.py   # 10 unit tests
    └── integration/
        ├── __init__.py
        ├── test_handoff.py  # Wave 4 stubs
        ├── test_mcp_tools.py
        ├── test_triage.py
        └── test_remediation.py
.github/workflows/base-image.yml
pyproject.toml
```

## Requirements Addressed

| REQ-ID | Description | Status |
|---|---|---|
| AGENT-002 | Typed JSON envelope for all inter-agent messages | ✅ Done |
| AGENT-007 | Per-session token budget tracked in Cosmos DB; $5 ceiling; 10 max iterations | ✅ Done |
| AGENT-008 | DefaultAzureCredential via managed identity; no credentials in code | ✅ Done |
| MONITOR-007 | OpenTelemetry spans with full AUDIT-001 fields | ✅ Done |
| AUDIT-001 | All 8 span attributes defined and exported | ✅ Done |
| AUDIT-005 | Agent action logs attributable to Entra Agent ID (AGENT_ENTRA_ID) | ✅ Done |

## Dependencies Unblocked

Plans 02-03 (API Gateway), 02-04 (Domain Agents), and 02-05 (Integration Tests) can now import from `agents.shared.*` for auth, telemetry, envelope, and budget tracking.
