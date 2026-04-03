# Phase 23: Change Correlation Engine - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (new service + API phase — discuss skipped)

<domain>
## Phase Boundary

Automatically correlate every incident with Azure resource changes in the preceding time window. When a DB degrades 4 minutes after a VM resize, that correlation surfaces automatically. The result is top-3 ChangeCorrelation objects attached to IncidentSummary, surfaces in AlertFeed badge.

**Requirement:** INTEL-002 — Change correlation surfaces correct cause within 30 seconds of incident creation

**What this phase does:**
1. Implement `services/api-gateway/change_correlator.py` — queries Activity Log via `azure.mgmt.monitor`, ranks changes by temporal proximity + topological distance + change type weight
2. Add `ChangeCorrelation` Pydantic model and `top_changes: list[ChangeCorrelation]` to `IncidentSummary`
3. Wire into `ingest_incident` as a BackgroundTask (like diagnostic_pipeline) — runs within 30 seconds
4. Store correlation results in Cosmos DB `incidents` container on the incident document
5. Add `GET /api/v1/incidents/{incident_id}/correlations` endpoint for on-demand refresh

**What this phase does NOT do:**
- Does not change the topology graph (Phase 22)
- Does not add UI changes (surfaces as data via API; UI integration deferred)
- Does not add new Terraform resources (Activity Log already exports to Log Analytics via activity-log module)

</domain>

<decisions>
## Implementation Decisions

### Data source: Azure Activity Log via `azure.mgmt.monitor`
- Already used in `diagnostic_pipeline.py` `_collect_activity_log()` — reuse the same pattern
- Query window: 30 minutes before incident `created_at` (configurable via env `CORRELATOR_WINDOW_MINUTES`, default 30)
- Scope: the incident's `resource_id` + all resources within its blast_radius (from Phase 22 topology)

### Correlation algorithm: weighted score
```
score = w_temporal * temporal_score + w_topology * topology_score + w_change_type * change_type_score
```
- **temporal_score** = `1.0 - (delta_minutes / window_minutes)` — changes closer in time score higher
- **topology_score** = `1.0 / (topology_distance + 1)` — same resource = 1.0, 1 hop = 0.5, 2 hops = 0.33
- **change_type_score** based on operation type:
  - `Microsoft.Compute/virtualMachines/write` (resize/redeploy) = 0.9
  - `Microsoft.Sql/servers/databases/write` = 0.8
  - `Microsoft.Network/networkSecurityGroups/write` = 0.8
  - `Microsoft.Resources/deployments/write` = 0.7
  - `Microsoft.Authorization/roleAssignments/write` = 0.6
  - everything else = 0.4
- **Weights**: `w_temporal=0.5, w_topology=0.3, w_change_type=0.2`
- Return top 3 by score

### ChangeCorrelation Pydantic model
```python
class ChangeCorrelation(BaseModel):
    change_id: str              # activity log event ID
    operation_name: str         # e.g. "Microsoft.Compute/virtualMachines/write"
    resource_id: str            # ARM resource ID of changed resource
    resource_name: str          # last path segment
    caller: Optional[str]       # UPN/object ID who made the change
    changed_at: str             # ISO8601 timestamp
    delta_minutes: float        # minutes before incident
    topology_distance: int      # hop count from incident resource (0 = same)
    change_type_score: float
    correlation_score: float    # overall weighted score 0.0..1.0
    status: str                 # "Succeeded" | "Failed" | "Started"
```

### Execution: BackgroundTask on incident ingestion (INTEL-002: within 30 seconds)
- Fire `correlate_incident_changes()` as BackgroundTask after `ingest_incident`
- Timeout: 25 seconds (5s headroom before INTEL-002 limit)
- Store in Cosmos `incidents` container: update `top_changes` field on the incident document
- `GET /api/v1/incidents/{incident_id}` already reads from Cosmos — if `top_changes` is populated it will be returned automatically via `IncidentSummary`

### Storage: Cosmos DB incidents container (existing)
- Update the incident document in-place by adding `top_changes: [...]` field
- No new Cosmos container needed — follows same pattern as diagnostic_pipeline updating `investigation_status`

</decisions>

<code_context>
## Existing Code Insights

### Reusable Patterns
- `services/api-gateway/diagnostic_pipeline.py` — `_collect_activity_log()` uses `azure.mgmt.monitor.MonitorManagementClient` + `activity_logs.list(filter=...)` — reuse verbatim
- `services/api-gateway/topology.py` — `TopologyClient.get_blast_radius(resource_id)` — use to get topologically-related resources for expanded correlation scope
- `services/api-gateway/main.py` — `BackgroundTasks` pattern for `run_diagnostic_pipeline` — use same pattern for `run_change_correlator`
- `services/api-gateway/dependencies.py` — `get_cosmos_client`, `get_credential`

### Activity Log query pattern (from diagnostic_pipeline.py)
```python
from azure.mgmt.monitor import MonitorManagementClient
sub_id = _extract_subscription_id(resource_id)
start = datetime.now(timezone.utc) - timedelta(hours=2)
filter_str = f"eventTimestamp ge '{start.isoformat()}' and resourceId eq '{resource_id}'"
client = MonitorManagementClient(credential, sub_id)
events = list(client.activity_logs.list(filter=filter_str))
```

### Log Analytics alternative
- Activity Log is also in Log Analytics (`AzureActivity` table) via the `activity-log` terraform module
- Could use `azure.monitor.query.LogsQueryClient` instead — more powerful KQL
- Decision: use `azure.mgmt.monitor` for consistency with existing `diagnostic_pipeline.py`

### IncidentSummary location
```python
# services/api-gateway/models.py line ~183
class IncidentSummary(BaseModel):
    incident_id: str
    severity: str
    domain: str
    status: str
    created_at: str
    title: Optional[str] = None
    resource_id: Optional[str] = None
    ...
    investigation_status: Optional[str] = None
    evidence_collected_at: Optional[str] = None
    # PHASE 22 added:
    # blast_radius_summary: Optional[dict] = None  (on IncidentResponse, not IncidentSummary)
```

### Incidents list endpoint
- `GET /api/v1/incidents` in `services/api-gateway/incidents_list.py` — reads from Cosmos
- `GET /api/v1/incidents/{incident_id}` may not exist yet — check before implementing
- The `top_changes` field stored in Cosmos will flow through automatically if IncidentSummary includes it

### Existing env vars
- `COSMOS_ENDPOINT` — Cosmos DB connection
- `LOG_ANALYTICS_WORKSPACE_ID` — Log Analytics
- `SUBSCRIPTION_IDS` — comma-separated subscription list

</code_context>

<specifics>
## Specific Ideas

### Correlation window expansion using topology
When incident has `resource_id = vm-prod-01`:
1. Get blast_radius(vm-prod-01) → [nic-01, subnet-default, vnet-prod, disk-01]
2. Query Activity Log for EACH of those resource_ids in the 30-min window
3. Score and rank all change events across all queried resources
4. topology_distance for vm-prod-01 changes = 0, for nic-01 = 1, for subnet = 2, etc.

### `correlate_incident_changes` function signature
```python
async def correlate_incident_changes(
    incident_id: str,
    resource_id: str,
    incident_created_at: datetime,
    credential: Any,
    cosmos_client: CosmosClient,
    topology_client: Optional[TopologyClient],
    window_minutes: int = 30,
    max_correlations: int = 3,
) -> None
```

### New endpoint
`GET /api/v1/incidents/{incident_id}/correlations` — returns `list[ChangeCorrelation]` from Cosmos
- This is separate from `/evidence` which returns diagnostic data

</specifics>

<deferred>
## Deferred Ideas

- Kubernetes resource change tracking (would require Arc MCP server extension)
- Policy compliance change correlation (too noisy; defer)
- UI badge for change correlation count (Phase 24 UI work)
- ML-based correlation scoring (rule-based weighted score is sufficient for INTEL-002)

</deferred>

---

*Phase: 23-change-correlation-engine*
*Context gathered: 2026-04-03 via autonomous mode*
