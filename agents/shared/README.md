# Shared Utilities

Common library used by all domain agents. Provides authentication helpers, telemetry setup, the typed incident message envelope, domain routing logic, human-in-the-loop (HITL) approval management, runbook retrieval, SOP (standard operating procedure) loading and notification, and budget tracking. No agent-specific business logic lives here.

## Responsibilities
- Provide `DefaultAzureCredential`-based auth and Foundry client factory (`auth.py`)
- Define `IncidentMessage` typed envelope for all inter-agent messages (`envelope.py`)
- Implement domain keyword + ARM resource type routing used by the orchestrator (`routing.py`)
- Manage HITL approval records in Cosmos DB (`approval_manager.py`)
- Expose runbook RAG retrieval via pgvector semantic search (`runbook_tool.py`)
- Load, store, and notify on SOPs (`sop_loader.py`, `sop_store.py`, `sop_notify.py`)
- Instrument all agents with OpenTelemetry traces and metrics (`otel.py`, `telemetry.py`)
- Track subscription spend against budgets (`budget.py`)

## Key Files
- `auth.py` — `get_foundry_client()`, `get_credential()`, `get_agent_identity()`
- `envelope.py` — `IncidentMessage`, `validate_envelope()`
- `routing.py` — `RESOURCE_TYPE_TO_DOMAIN`, `QUERY_DOMAIN_KEYWORDS`, `classify_query_text()`
- `approval_manager.py` — create/read/update HITL approval records in Cosmos DB
- `runbook_tool.py` — `retrieve_runbooks()` pgvector semantic search wrapper
- `otel.py` — OpenTelemetry tracer setup and `instrument_tool_call()` decorator
- `telemetry.py` — structured logging and metric emission helpers
- `budget.py` — subscription budget tracking utilities
- `subscription_utils.py` — `extract_subscription_id()` from ARM resource IDs
- `sop_loader.py` / `sop_store.py` / `sop_notify.py` — SOP lifecycle management
- `triage.py` — shared triage step helpers (Activity Log prefix, confidence scoring)
- `gitops.py` — GitOps configuration helpers for Arc Kubernetes
- `resource_identity.py` — ARM resource ID parsing utilities
- `logging_config.py` — structured JSON logging configuration
