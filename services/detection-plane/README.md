# Detection Plane

Event-driven alert detection pipeline that converts Azure Monitor signals into AAP incidents. The pipeline flows: Azure Monitor → Azure Event Hubs → Fabric Eventhouse (KQL) → Fabric Activator → `POST /api/v1/incidents` on the API Gateway.

## Tech Stack
- Python (installable package via `pyproject.toml`)
- Azure Event Hubs (ingestion source)
- Microsoft Fabric Eventhouse (KQL time-series storage)
- Microsoft Fabric Activator (threshold-based event detection and webhook trigger)
- Pydantic (payload validation and modelling)

## Key Files / Directories

- `models.py` — Pydantic models: `DetectionEvent`, `IncidentPayload`, alert severity enums
- `payload_mapper.py` — Transforms raw Azure Monitor / Event Hub payloads into normalized `IncidentPayload` objects
- `classify_domain.py` — KQL `classify_domain()` logic ported to Python; maps resource type / alert name to AAP domain (`compute`, `network`, `storage`, `security`, etc.)
- `dedup.py` — In-process deduplication logic (fingerprint-based); mirrors the dedup module deployed in the API Gateway
- `alert_state.py` — Alert lifecycle state machine (`new → active → resolved`)
- `SUPPRESSION.md` — Operational runbook for managing alert suppression windows
- `pyproject.toml` — Package definition (`aap-detection-plane`)
- `docs/` — Architecture diagrams and KQL query reference
- `tests/` — Pytest unit tests for domain classification, payload mapping, and dedup

## Running Locally

```bash
cd services/detection-plane
pip install -e ".[dev]"
pytest tests/
```

> The detection plane library is consumed by the API Gateway (`dedup_integration.py`) and by Fabric User Data Functions triggered by Activator. It is not a standalone server.
