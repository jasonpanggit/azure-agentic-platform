# Phase 28: Platform Intelligence - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning
**Mode:** Auto-generated (new service + API phase — discuss skipped)

<domain>
## Phase Boundary

Transform the platform from a reactive-only system into one that generates actionable, platform-wide intelligence from everything it has observed: incidents, remediations, approvals, SLOs, forecasts, and operator feedback. Phase 28 is the final phase of the v2.0 milestone.

**Requirements:**
- PLATINT-001: Systemic pattern analysis runs on schedule; top-5 recurring issues surfaced in UI
- PLATINT-002: FinOps integration tracks incident cost impact and automation savings
- PLATINT-003: Operator feedback (approve/reject) captured and fed to learning loop
- PLATINT-004: `POST /api/v1/admin/business-tiers` available; zero-value default config seeded on Phase 28 deployment

**What this phase does:**
1. `services/api-gateway/pattern_analyzer.py` — k-means-style clustering (pure Python, no sklearn) on incident history; identifies top-5 recurring issue patterns; runs on a weekly schedule as a background task; stores results in Cosmos `pattern_analysis` container
2. New Cosmos container `pattern_analysis` (partition `/analysis_date`) + Terraform
3. New endpoints: `GET /api/v1/intelligence/patterns` (latest pattern analysis), `GET /api/v1/intelligence/health-score` (platform health metrics), `POST /api/v1/admin/business-tiers` + `GET /api/v1/admin/business-tiers`
4. `services/api-gateway/finops_tracker.py` — queries Azure Cost Management API for VM/resource costs; computes `cost_saved_by_automation` from remediation_audit records (actions taken vs. estimated incident duration × hourly rate); stores FinOps summary in Cosmos `pattern_analysis` container
5. Operator feedback loop: extend `POST /api/v1/approvals/{id}/approve` and `POST /api/v1/approvals/{id}/reject` to capture optional `feedback_text` and `feedback_tags` fields on the approval record; store these in Cosmos approvals container + feed to pattern analyzer on next run
6. Platform Health dashboard API: `GET /api/v1/intelligence/platform-health` — returns: detection_pipeline_lag_seconds, agent_p50_ms, agent_p95_ms, auto_remediation_success_rate, slo_compliance_pct, error_budget_portfolio, noise_reduction_pct, automation_savings_count
7. Business tiers: `POST /api/v1/admin/business-tiers` stores operator-configured revenue tiers (tier name + monthly_revenue_usd + associated resource_tags); seeded with zero-value default on startup

**What this phase does NOT do:**
- Does not add a FinOps tab to the dashboard UI (API only; UI deferred)
- Does not use sklearn, numpy, or scipy — pure Python k-means-style grouping
- Does not change existing approval endpoints' response format (feedback fields are optional additions)
- Does not integrate with Azure Cost Management billing API requiring EA enrollment (uses public pricing API or estimates)

</domain>

<decisions>
## Implementation Decisions

### Cosmos container: `pattern_analysis`
- Partition key: `/analysis_date` (e.g. "2026-04-07")
- Stores: weekly pattern run results + FinOps summaries + platform health snapshots
- No TTL initially (compliance requirement similar to remediation_audit)
- One document per weekly run: `{ id: "pattern-{date}", analysis_date: "{date}", top_patterns: [...], finops_summary: {...}, platform_health: {...} }`

### Cosmos container: `business_tiers`
- Partition key: `/tier_name`
- Schema: `{ id: tier_name, tier_name: str, monthly_revenue_usd: float, resource_tags: dict, created_at: str, updated_at: str }`
- Seeded at startup with `{ tier_name: "default", monthly_revenue_usd: 0.0, resource_tags: {} }` if container is empty

### Pattern analysis algorithm (pure Python, no sklearn)
Simple centroid-based grouping on incident features:
```python
# Group incidents by (domain, resource_type, detection_rule) tuple
# For each group: count, frequency (incidents/week), avg_severity_score
# Top-5 by frequency × avg_severity_score
# "Pattern" = { pattern_id, domain, resource_type, detection_rule, incident_count, frequency_per_week, avg_severity, top_title_words, first_seen, last_seen }
```
No actual k-means needed — feature tuple grouping achieves PLATINT-001 goal with zero dependencies.

### FinOps tracking (PLATINT-002)
Two metrics:
1. **Wasted compute** — query `incidents` container for compute domain incidents lasting >30 min. Multiply by estimated hourly rate from `business_tiers` or default `$0.10/hour` per affected resource.
2. **Automation savings** — from `remediation_audit` container: count `status="complete"` execute records. Multiply by `FINOPS_SAVINGS_PER_REMEDIATION_MINUTES` env var (default: "30") × hourly rate. Represents estimated operator time saved.

No call to Azure Cost Management billing API (requires EA enrollment). Use estimates based on business tier config.

### Feedback capture (PLATINT-003)
Extend `process_approval_decision` in `approvals.py` to accept optional `feedback_text: Optional[str]` and `feedback_tags: Optional[list[str]]` parameters. Store on the Cosmos approval record. The pattern_analyzer reads these when building its weekly analysis.

Pattern analyzer uses feedback to:
- Mark patterns with `operator_flagged: True` if ≥2 approvals for that pattern have `feedback_tags` containing "false_positive" or "not_useful"
- Include `common_feedback` field: top 3 most frequent feedback_tags for each pattern

### Business tiers (PLATINT-004)
```python
class BusinessTier(BaseModel):
    id: str                        # same as tier_name
    tier_name: str
    monthly_revenue_usd: float     # 0.0 = not configured
    resource_tags: dict            # e.g. {"environment": "production"}
    created_at: str
    updated_at: str
```
`GET /api/v1/admin/business-tiers` — returns list of all tiers
`POST /api/v1/admin/business-tiers` — upsert a tier (create or update)

Startup seeding: check if container has any items; if empty, seed the default zero-value tier.

### Platform health endpoint (GET /api/v1/intelligence/platform-health)
Aggregates from existing data:
- `detection_pipeline_lag_seconds`: last `det-` incident `created_at` timestamp age (how long ago last detection fired)
- `auto_remediation_success_rate`: (complete / (complete + failed)) from remediation_audit last 7d
- `noise_reduction_pct`: from incidents container last 24h (suppressed_cascade / total)
- `slo_compliance_pct`: % of SLOs with status="healthy" in slo_definitions table
- `automation_savings_count`: count of complete remediation executions last 30d
- `agent_p50_ms` / `agent_p95_ms`: Not available without App Insights query — return None (deferred, requires separate metrics integration)
- `error_budget_portfolio`: list of {slo_id, error_budget_pct} for all SLOs

### Background schedule: weekly pattern analysis
Runs every 7 days (604800 seconds) starting from first lifespan startup. Pattern analyzer also runs immediately at startup if no analysis exists from the past 7 days.

### PatternResult and PlatformHealth Pydantic models
```python
class IncidentPattern(BaseModel):
    pattern_id: str
    domain: str
    resource_type: Optional[str]
    detection_rule: Optional[str]
    incident_count: int
    frequency_per_week: float
    avg_severity_score: float
    top_title_words: list[str]
    first_seen: str
    last_seen: str
    operator_flagged: bool = False
    common_feedback: list[str] = []

class PatternAnalysisResult(BaseModel):
    analysis_id: str
    analysis_date: str
    period_days: int
    total_incidents_analyzed: int
    top_patterns: list[IncidentPattern]
    finops_summary: dict
    generated_at: str

class PlatformHealth(BaseModel):
    detection_pipeline_lag_seconds: Optional[float]
    auto_remediation_success_rate: Optional[float]
    noise_reduction_pct: Optional[float]
    slo_compliance_pct: Optional[float]
    automation_savings_count: int
    agent_p50_ms: Optional[float]    # None until App Insights integration
    agent_p95_ms: Optional[float]    # None until App Insights integration
    error_budget_portfolio: list[dict]
    generated_at: str
```

### Environment variables
- `PATTERN_ANALYSIS_ENABLED` (default: "true")
- `PATTERN_ANALYSIS_INTERVAL_SECONDS` (default: "604800" — 7 days)
- `PATTERN_ANALYSIS_LOOKBACK_DAYS` (default: "30")
- `FINOPS_SAVINGS_PER_REMEDIATION_MINUTES` (default: "30")
- `FINOPS_HOURLY_RATE_USD` (default: "0.10")
- `COSMOS_PATTERN_ANALYSIS_CONTAINER` (default: "pattern_analysis")
- `COSMOS_BUSINESS_TIERS_CONTAINER` (default: "business_tiers")

</decisions>

<code_context>
## Existing Code Insights

### approvals.py pattern
- `process_approval_decision(approval_id, thread_id, decision, decided_by)` — extend to accept `feedback_text` and `feedback_tags`
- Cosmos approval record already has: `decided_by`, `decided_at`, `status`
- PLATINT-003: add `feedback_text: Optional[str]` and `feedback_tags: Optional[list[str]]` to the Cosmos write

### existing Cosmos query pattern (from incidents_list.py, noise_reducer.py)
```python
container = cosmos_client.get_database_client("aap").get_container_client("incidents")
items = list(container.query_items(query="SELECT ...", enable_cross_partition_query=True))
```

### ApprovalAction model (models.py) — extend for PLATINT-003
```python
class ApprovalAction(BaseModel):
    decided_by: str
    feedback_text: Optional[str] = None      # NEW
    feedback_tags: Optional[list[str]] = []   # NEW — e.g. ["false_positive", "not_useful"]
```

### Background task pattern (from topology.py, forecaster.py)
```python
async def run_pattern_analysis_loop(cosmos_client, interval_seconds=604800):
    while True:
        await asyncio.sleep(interval_seconds)
        await _run_pattern_analysis(cosmos_client)
```

### Startup seeding pattern
```python
# In lifespan, after migrations:
await _seed_default_business_tier(cosmos_client)
```

### slo_tracker.py — reuse for slo_compliance_pct
```python
from services.api_gateway.slo_tracker import list_slos
slos = await list_slos(postgres_conn)
slo_compliance_pct = len([s for s in slos if s["status"] == "healthy"]) / len(slos) * 100
```

### Remediation audit query for automation savings
```python
container = _get_remediation_audit_container(cosmos_client)
query = "SELECT * FROM c WHERE c.status = 'complete' AND c.action_type = 'execute' AND c.executed_at >= @cutoff"
```

</code_context>

<deferred>
## Deferred

- FinOps tab in dashboard UI (frontend deferred)
- Azure Cost Management API integration (requires EA enrollment)
- Agent P50/P95 latency from App Insights (requires App Insights query integration — deferred)
- ML-based pattern analysis (k-means-tuple-grouping achieves PLATINT-001)
- Multi-week trend charts for UI (API returns raw data; visualization deferred)

</deferred>

---
*Phase: 28-platform-intelligence*
*Context gathered: 2026-04-04 via autonomous mode*
