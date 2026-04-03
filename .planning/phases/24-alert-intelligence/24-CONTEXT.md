# Phase 24: Alert Intelligence and Noise Reduction - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (new service + API phase — discuss skipped)

<domain>
## Phase Boundary

Reduce alert noise by ≥80% through three mechanisms:
1. **Causal suppression** — when blast_radius of a known incident contains a new alert's resource_id, suppress the new alert as a downstream cascade
2. **Multi-dimensional correlation** — group alerts by temporal + topological + semantic similarity into correlated groups, routing later duplicates to the existing incident thread
3. **Composite severity scoring** — re-weight severity based on blast_radius size, SLO risk, and business tier

**Requirement:** INTEL-001 — Alert noise reduction ≥80% on correlated alert storm simulations

**What this phase does:**
1. `services/api-gateway/noise_reducer.py` — causal suppression logic using topology, correlation grouping using sliding time window + blast_radius overlap, composite severity scorer
2. Wire into `ingest_incident` BEFORE Foundry dispatch — suppress or re-route cascades, compute composite severity
3. Add `composite_severity` field to `IncidentPayload` and `IncidentSummary`
4. Add `GET /api/v1/incidents/stats` endpoint — noise reduction metrics (suppressed_count, correlated_count, period)
5. Simulation test: inject 10 correlated storm alerts from a shared topology neighborhood, assert ≥8 are suppressed or correlated (≥80% reduction)

**What this phase does NOT do:**
- Does not change the detection pipeline (Phase 21)
- Does not add UI changes (noise metrics via API only; Observability tab integration deferred)
- Does not change SLO definition (Phase 25 handles SLO tracking)

</domain>

<decisions>
## Implementation Decisions

### Causal suppression algorithm
```
For a new incident with resource_id R:
1. Query recent active incidents (status NOT 'closed', created_at > now - 2h) from Cosmos
2. For each active incident I: get I.blast_radius_summary (Phase 22 attached this)
3. If R is in I.blast_radius_summary['affected_resources'], suppress new incident:
   - Set status = 'suppressed_cascade'
   - Link to parent incident I.incident_id
   - Do NOT dispatch to Foundry
   - Return IncidentResponse with suppressed=True, parent_incident_id
```

### Multi-dimensional correlation (extends existing dedup)
- Time window: 10 minutes sliding
- If new incident shares same domain + any topology neighbor + fired_at within 10 minutes of existing active incident → correlate (route to same Foundry thread)
- This extends Phase 22 dedup_integration.py logic (which only does exact resource_id + rule matching)
- Correlation precedence: suppression first, then correlation, then new incident

### Composite severity scoring
```
composite_severity_score = (
    base_severity_weight(payload.severity) +     # Sev0=1.0, Sev1=0.8, Sev2=0.6, Sev3=0.4
    0.3 * blast_radius_score(blast_radius_size) +  # log10(n+1)/log10(101) capped at 1.0
    0.2 * slo_risk_score(domain)                   # domain risk weights
)
composite_severity = "Sev0" if score >= 0.9 else "Sev1" if score >= 0.7 else "Sev2" if score >= 0.5 else "Sev3"
```

Domain SLO risk weights:
- compute = 0.9, network = 0.85, storage = 0.8, database = 0.8, security = 1.0, sre = 0.7, arc = 0.6, patch = 0.4

### Storage: no new containers
- `suppressed_incidents` stored in existing `incidents` container with status='suppressed_cascade' + parent_incident_id field
- Noise metrics computed on-the-fly from Cosmos query (not pre-aggregated)

### Noise metrics endpoint
`GET /api/v1/incidents/stats?window_hours=24` → `{ total: int, suppressed: int, correlated: int, new: int, noise_reduction_pct: float, window_hours: int }`

### Simulation test (INTEL-001 validation)
Script `scripts/ops/24-3-noise-reduction-test.sh`:
- Sends 10 POST /api/v1/incidents in rapid succession from the same topology cluster (same blast_radius)
- First incident creates root cause
- Incidents 2-10 should be suppressed or correlated
- Assert ≥8 of 10 are NOT new Foundry threads (≥80% suppression/correlation)
- Reports INTEL-001 PASS/FAIL

</decisions>

<code_context>
## Existing Code Insights

### Reusable Patterns
- `services/api-gateway/dedup_integration.py` — existing 2-layer dedup; Phase 24 suppression runs BEFORE dedup (suppression > dedup > new incident)
- `services/api-gateway/change_correlator.py` — Pattern for BackgroundTask-style async functions
- `services/api-gateway/topology.py` — `TopologyClient.get_blast_radius()` — key to suppression
- `services/api-gateway/main.py` — `ingest_incident` handler flow: dedup → (if not dup) → Foundry thread → background tasks

### Incident ingestion flow (from main.py)
```
ingest_incident:
  1. dedup check (check_dedup)
  2. if dedup hit → return early
  3. create_foundry_thread
  4. persist to Cosmos
  5. BackgroundTask: run_diagnostic_pipeline
  6. BackgroundTask: correlate_incident_changes
  7. return IncidentResponse
```

Phase 24 inserts BEFORE step 1:
```
  0a. get_blast_radius for new incident resource_id (topology check)
  0b. query active incidents for causal suppression
  0c. if suppressed → store suppressed incident + return early (no Foundry thread)
  0d. compute composite_severity
  [then continue with step 1: dedup check]
```

### Cosmos query for active incidents
```python
from azure.cosmos import CosmosClient
container = cosmos_client.get_database_client("aap").get_container_client("incidents")
query = """
SELECT c.incident_id, c.resource_id, c.blast_radius_summary, c.created_at, c.status
FROM c
WHERE c.status NOT IN ('closed', 'suppressed_cascade')
AND c._ts > @cutoff
"""
```

### IncidentSummary additions needed
- `composite_severity: Optional[str] = None` — re-weighted severity
- `suppressed: Optional[bool] = None` — True if this is a suppressed cascade
- `parent_incident_id: Optional[str] = None` — incident that caused suppression

### Environment variables
- `NOISE_SUPPRESSION_ENABLED` (default: "true") — feature flag for causal suppression
- `NOISE_CORRELATION_WINDOW_MINUTES` (default: "10") — sliding window
- `NOISE_SUPPRESSION_LOOKBACK_HOURS` (default: "2") — how far back to check active incidents

</code_context>

<specifics>
## Specific Ideas

### Suppression response (no Foundry thread created)
When suppressed, `ingest_incident` returns:
```python
return IncidentResponse(
    thread_id="suppressed",
    incident_id=payload.incident_id,
    status="suppressed_cascade",
    suppressed=True,
    parent_incident_id=parent_id,
)
```
IncidentResponse needs `suppressed: Optional[bool] = None` and `parent_incident_id: Optional[str] = None` added.

### Noise metrics query
```python
GET /api/v1/incidents/stats?window_hours=24
→ {
    total: 150,
    suppressed: 95,
    correlated: 25,
    new: 30,
    noise_reduction_pct: 80.0,
    window_hours: 24
}
```
noise_reduction_pct = (suppressed + correlated) / total * 100

</specifics>

<deferred>
## Deferred Ideas

- UI noise metrics in Observability tab (deferred — surface via API only)
- Business tier weighting (requires business_tier config from Phase 28)
- ML-based suppression (rule-based is sufficient for INTEL-001)
- Semantic similarity grouping (requires embedding comparison — too expensive; topological + temporal is sufficient)

</deferred>

---

*Phase: 24-alert-intelligence*
*Context gathered: 2026-04-03 via autonomous mode*
