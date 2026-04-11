# Phase 23 — Change Correlation Engine: Summary

## What Was Built

### Wave 1 (Plan 23-1): Change Correlator Service
- `services/api-gateway/change_correlator.py` — 321-line async engine that:
  - Queries Azure Activity Log for write/action events on the incident's primary resource and all topology neighbors
  - Scores each event by temporal proximity (50%), topological distance (30%), and change type (20%)
  - Persists top-3 `ChangeCorrelation` objects to the Cosmos `incidents` container (field: `top_changes`)
  - Never raises — all failures logged; partial results preferred over none
- `services/api_gateway/models.py` — `ChangeCorrelation` Pydantic model + `top_changes: Optional[list[ChangeCorrelation]]` on `IncidentSummary`
- 20 unit tests in `test_change_correlator.py`

### Wave 2 (Plan 23-2): Incident Wiring + Correlations Endpoint
- **`services/api-gateway/main.py`**:
  - Added `from services.api_gateway.change_correlator import correlate_incident_changes` import
  - Added `ChangeCorrelation` to the models import block
  - Moved `topology_client = getattr(request.app.state, "topology_client", None)` before the `if payload.affected_resources:` block so it's available to both the correlator task and the TOPO-004 blast-radius prefetch
  - Added `background_tasks.add_task(correlate_incident_changes, ...)` inside `ingest_incident`, after `run_diagnostic_pipeline` (ordering preserved)
  - Added `GET /api/v1/incidents/{incident_id}/correlations` endpoint — returns `list[ChangeCorrelation]`, 200+empty-list when unpopulated, 404 for unknown incident, 503 for no Cosmos
- **`services/api-gateway/incidents_list.py`**:
  - Added `c.top_changes` to the Cosmos SELECT projection
  - Added `"top_changes": doc.get("top_changes")` to `enriched_doc`
- **`services/api-gateway/tests/test_change_correlator_wiring.py`** — 7 new tests:
  - `test_ingest_incident_queues_correlator` — correlator is queued as BackgroundTask
  - `test_ingest_incident_correlator_queued_after_pipeline` — ordering preserved
  - `test_ingest_incident_no_resources_skips_correlator` — 422 on bad payload, no correlator queued
  - `test_get_correlations_returns_top_changes` — 200 with ChangeCorrelation list
  - `test_get_correlations_returns_empty_list_when_not_populated` — 200 with `[]`
  - `test_get_correlations_404_for_unknown_incident` — 404 on missing doc
  - `test_get_correlations_503_when_cosmos_not_configured` — 503 when cosmos=None

## Test Results

- **Phase 23 total:** 27 new tests (20 from Wave 1 + 7 from Wave 2), all passing
- **Full suite:** 415 passed, 2 skipped, 0 failed — zero regressions

## Requirement Satisfied

**INTEL-002:** Change correlation surfaces correct cause within 30 seconds of incident creation. The correlator fires as a background task immediately after ingestion and writes `top_changes` to the incident document. Operators can retrieve correlations via `GET /api/v1/incidents/{id}/correlations`.
