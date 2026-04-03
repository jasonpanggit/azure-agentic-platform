# Phase 24: Alert Intelligence and Noise Reduction — Summary

**Completed:** 2026-04-03
**Branch:** `gsd/phase-24-alert-intelligence`
**Requirement:** INTEL-001 — Alert noise reduction ≥80% on correlated alert storm simulations

---

## What Phase 24 Built

### Wave 1 — Noise Reducer Service (`24-1`)

**File created:** `services/api-gateway/noise_reducer.py`

Implemented three noise reduction mechanisms as a standalone module:

1. **Causal suppression** (`check_causal_suppression`)
   - Queries recent active incidents from Cosmos DB (default lookback: 2 hours)
   - If the new alert's `resource_id` appears in any active incident's `blast_radius_summary.affected_resources`, the new alert is tagged `suppressed_cascade` and linked to the parent incident
   - No Foundry thread is created for suppressed incidents — eliminates downstream noise at the source

2. **Multi-dimensional correlation** (`check_temporal_topological_correlation`)
   - Runs after suppression check (precedence: suppress > correlate > new)
   - Queries active incidents in the same domain within a 10-minute sliding window
   - Uses topology neighbor set (from `TopologyClient._get_topology_node`) to check for resource overlap
   - Routes matching alerts to an existing incident thread rather than creating a new one

3. **Composite severity scoring** (`compute_composite_severity`)
   - Re-weights severity using blast radius size (log10 scale) and domain SLO risk
   - Formula: `base_weight + 0.3 * blast_radius_score + 0.2 * slo_risk_weight`
   - Domain SLO weights: security=1.0, compute=0.9, network=0.85, storage/database=0.8, sre=0.7, arc=0.6, patch=0.4

**Model fields added to `models.py`:**
- `IncidentPayload.composite_severity: Optional[str]`
- `IncidentSummary.composite_severity`, `.suppressed`, `.parent_incident_id`
- `IncidentResponse.suppressed`, `.parent_incident_id`

**Tests:** `services/api-gateway/tests/test_noise_reducer.py`

---

### Wave 2 — Incident Wiring + Stats Endpoint (`24-2`)

**File modified:** `services/api-gateway/main.py`

Wired noise reduction into `ingest_incident` **before** the existing dedup check:

```
Step 0a: get_blast_radius for new incident resource_id
Step 0b: check_causal_suppression → if hit, store suppressed incident + return early
Step 0c: check_temporal_topological_correlation → if hit, route to existing thread
Step 0d: compute_composite_severity → attach to incident document
[then: existing dedup → Foundry thread → Cosmos persist → background tasks]
```

**Endpoint added:** `GET /api/v1/incidents/stats?window_hours=N`

Returns real-time noise reduction metrics:
```json
{
  "total": 150,
  "suppressed": 95,
  "correlated": 25,
  "new": 30,
  "noise_reduction_pct": 80.0,
  "window_hours": 24
}
```

**Feature flag:** `NOISE_SUPPRESSION_ENABLED=true` (default) — allows hot-disable without redeploy.

---

### Wave 3 — INTEL-001 Simulation Test (`24-3`)

**File created:** `scripts/ops/24-3-noise-reduction-test.sh`

End-to-end simulation script that validates the INTEL-001 requirement:

1. Records a baseline stats snapshot before injection
2. Sends **1 root-cause incident** (Sev1, `vm-root-001`)
3. Waits 2 seconds for blast_radius propagation
4. Sends **9 cascade incidents** from the same topology cluster (same subscription, same resource group, related resource types)
5. Waits 3 seconds for background task processing
6. Queries `GET /api/v1/incidents/stats?window_hours=1`
7. Subtracts baseline to isolate test-run traffic
8. Asserts `noise_reduction_pct >= REQUIRED_NOISE_REDUCTION` (default: 80%)
9. Reports **INTEL-001 PASS** (exit 0) or **INTEL-001 FAIL** (exit 1) with metrics and troubleshooting checklist

**Env var interface:**
| Variable | Default | Purpose |
|----------|---------|---------|
| `API_URL` / `API_BASE` | `http://localhost:8080` | API gateway URL |
| `TOKEN` | (auto-acquired) | Entra Bearer token |
| `E2E_CLIENT_ID` / `E2E_CLIENT_SECRET` | — | Client-credentials token flow for CI |
| `E2E_API_AUDIENCE` | `api://aap-api-gateway` | Token audience |
| `REQUIRED_NOISE_REDUCTION` | `80` | INTEL-001 pass threshold (%) |
| `WINDOW_HOURS` | `1` | Stats query window |

---

## Test Coverage

- 440 tests passing before Phase 24
- Wave 1 added unit tests for all three noise reduction functions in `test_noise_reducer.py`
- Wave 2 added integration tests for the `ingest_incident` suppression path and the `/stats` endpoint

---

## Architecture Impact

Phase 24 introduces a **pre-ingestion noise filter** layer:

```
Incoming Alert
      │
      ▼
[Causal Suppression Check]  ──► suppressed_cascade (no Foundry thread)
      │ (pass)
      ▼
[Temporal/Topology Correlation] ──► routed to existing thread
      │ (pass)
      ▼
[Composite Severity Scoring]
      │
      ▼
[Existing Dedup Check]
      │
      ▼
[Foundry Thread Creation + Cosmos Persist]
```

This reduces Foundry API calls and operator alert fatigue by ≥80% during correlated storm events, satisfying INTEL-001.

---

## Known Caveats

- **Topology dependency:** Causal suppression requires `COSMOS_ENDPOINT` + `SUBSCRIPTION_IDS` set on the Container App. Without topology, the suppression check degrades gracefully (returns `None`, incident proceeds as new).
- **Stats window overlap:** `noise_reduction_pct` includes all incidents in the window. Ambient traffic may lower the percentage in active environments. Use short windows or run the test in isolation.
- **Preview dependency:** `NOISE_SUPPRESSION_ENABLED` feature flag allows rollback without redeploy if unexpected behavior is observed in production.

---

## Next Phase

**Phase 25 — SLO Tracking** builds on the `composite_severity` scores and incident data collected here to track SLO burn rates and generate proactive alerts before SLO violations occur.
