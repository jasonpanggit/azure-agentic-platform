# API Gateway

FastAPI thin router that receives chat and operational API requests and forwards them to domain specialist agents via Azure AI Foundry. Contains no business logic — all incident reasoning is deferred to Foundry agent threads.

## Tech Stack
- Python / FastAPI
- Azure AI Foundry (`azure-ai-projects`)
- Azure Cosmos DB (incidents, sessions, approvals)
- OpenTelemetry (`instrumentation.py`)
- Docker (Container Apps deployment)

## Key Files / Directories

- `main.py` — FastAPI app entry point; registers all routers and middleware
- `chat.py` — Primary chat endpoint; creates/continues Foundry agent threads
- `vm_chat.py` / `aks_chat_tools.py` / `vmss_chat_tools.py` — Resource-scoped chat tools
- `incidents_list.py` / `simulation_endpoints.py` — Incident ingestion and simulation
- `approvals.py` — Human-in-the-loop remediation approval state machine
- `foundry.py` — Azure AI Foundry client factory and agent routing helpers
- `topology.py` / `topology_tree.py` / `topology_endpoints.py` — Resource topology graph
- `audit.py` / `audit_trail.py` / `audit_export.py` — Audit log read/write
- `patch_endpoints.py` — VM patch assessment and history endpoints
- `eol_endpoints.py` — End-of-life detection endpoints (calls EOL agent)
- `dedup_integration.py` / `noise_reducer.py` — Alert deduplication and noise filtering
- `instrumentation.py` — OpenTelemetry tracing setup
- `dependencies.py` — Shared FastAPI `Depends()` helpers (Cosmos client, auth)
- `models.py` — Shared Pydantic request/response models
- `Dockerfile` — Container image definition
- `requirements.txt` — Python dependencies
- `tests/` — Pytest unit and integration tests (~656 tests)
- `evaluation/` — Agent evaluation harness

## Running Locally

```bash
cd services/api-gateway
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

> **Note:** Requires `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` (or managed identity), `COSMOS_ENDPOINT`, and `FOUNDRY_PROJECT_ENDPOINT` environment variables. See `.env.example` at the repo root.
