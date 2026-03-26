# Phase 4: Detection Plane - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

End-to-end Fabric detection pipeline — Azure Monitor alerts flow from Event Hub (ingest) → Eventhouse KQL enrichment pipeline (`RawAlerts` → `EnrichedAlerts` → `DetectionResults`) → Fabric Activator trigger → Fabric User Data Function → `POST /api/v1/incidents` on the existing API gateway. Alert deduplication (two-layer), alert state lifecycle tracking, and Activity Log OneLake mirroring are all in scope. Terraform provisions all Fabric resources (capacity, Eventhouse, Activator, OneLake) plus Event Hub namespace.

**No UI, no new agent capabilities, no new API gateway features.** The `POST /api/v1/incidents` endpoint is already live from Phase 2 — Phase 4 builds the detection plane that feeds it.

</domain>

<decisions>
## Implementation Decisions

### Fabric Terraform Module Structure
- **D-01:** **Single `terraform/modules/fabric/` module** provisions all Fabric resources together: Fabric capacity, Eventhouse (KQL database), Activator workspace, and OneLake lakehouse. One module, one apply, consistent with the per-domain module pattern established in Phase 1.
- **D-02:** **Fabric capacity is provisioned inside the module** (not pre-existing). The fabric module provisions capacity (F2 or F4 SKU per environment) fully via Terraform for reproducibility. Capacity resource: `azapi_resource` type `Microsoft.Fabric/capacities`.
- **D-03:** The existing `snet-reserved-1` subnet (10.0.64.0/24) provisioned in Phase 1 networking module is activated for Event Hub VNet integration in Phase 4. The networking module is extended, not re-created.

### KQL Schema & `classify_domain()` Logic
- **D-04:** **Three-table pipeline:** `RawAlerts` (raw Event Hub ingest) → `EnrichedAlerts` (resource inventory join added via KQL update policy) → `DetectionResults` (classified with `domain` field, ready for Activator). Matches DETECT-002 exactly.
- **D-05:** **`classify_domain()` uses ARM `resource_type` as the primary signal.** A KQL function maps ARM resource type prefixes to domains:
  - `Microsoft.Compute/*` → `compute`
  - `Microsoft.Network/*` → `network`
  - `Microsoft.Storage/*` → `storage`
  - `Microsoft.Security/*` → `security`
  - `Microsoft.HybridCompute/*` or `Microsoft.Kubernetes/connectedClusters` → `arc`
  - Any resource on a `Microsoft.HybridCompute` subscription or tagged for Arc → `arc`
  - All others → fallback (see D-06)
- **D-06:** **Unclassifiable alerts fallback to `domain = 'sre'`.** Alerts where `classify_domain()` cannot map the resource_type are assigned `domain = 'sre'` — routed to the SRE agent as the catch-all. Nothing is silently dropped; SRE triages unclassifiable alerts.

### Activator → API Gateway Call Path
- **D-07:** **Activator → Fabric User Data Function → `POST /api/v1/incidents`** (per DETECT-003). No Power Automate intermediary. The User Data Function is Python; it formats the DETECT-004 payload and calls the gateway.
- **D-08:** **Fabric User Data Function authenticates using a Service Principal (client credentials flow).** A dedicated app registration is provisioned for the Fabric integration. `client_id` and `client_secret` are stored in Key Vault (already provisioned in Phase 1) and injected into the User Data Function environment at deploy time. The API gateway's existing Entra Bearer token validation (D-10 from Phase 2) is unchanged.
- **D-09:** The Service Principal's app registration is provisioned via Terraform (`azuread` provider). The gateway's Entra app registration (from Phase 2) defines the authorized audience; the new Fabric Service Principal is granted `incidents.write` application role on the gateway app registration.

### Alert Deduplication (DETECT-005)
- **D-10:** **Cosmos DB `incidents` container — partition key: `resource_id`.** One logical partition per Azure resource. Efficient for the open-incident check query (layer 2): `SELECT * FROM incidents WHERE resource_id = @rid AND status = 'open'`.
- **D-11:** **Dedup layer 1 (time-window collapse):** Multiple alerts for the same `resource_id` + `detection_rule` within a 5-minute window are collapsed into a single Cosmos DB incident record. ETag optimistic concurrency (same pattern as `agents/shared/budget.py`) prevents lost-update races.
- **D-12:** **Dedup layer 2 (open-incident correlation):** When a new distinct alert arrives for a `resource_id` that already has an open incident, the new alert is **added to the existing incident's `correlated_alerts` array** (no new Cosmos record, no new agent thread). The Orchestrator receives all correlated alerts as context. The operator sees the correlated count alongside the original incident.
- **D-13:** **Incidents container schema:**
  ```json
  {
    "id": "<incident_id>",
    "resource_id": "<ARM resource ID>",      // partition key
    "incident_id": "<incident_id>",
    "severity": "Sev0|Sev1|Sev2|Sev3",
    "domain": "compute|network|storage|security|arc|sre",
    "detection_rule": "<rule name>",
    "kql_evidence": "<KQL results>",
    "status": "new|acknowledged|closed",
    "status_history": [{ "status": "new", "actor": "system", "timestamp": "..." }],
    "thread_id": "<Foundry thread ID>",
    "correlated_alerts": [],                 // array of correlated alert payloads
    "created_at": "<ISO 8601>",
    "updated_at": "<ISO 8601>",
    "_etag": "<Cosmos ETag>"
  }
  ```

### Alert State Lifecycle (DETECT-006)
- **D-14:** Alert state transitions (New → Acknowledged → Closed) are tracked in `incidents.status` + `incidents.status_history` in Cosmos DB, with actor (agent ID or operator UPN) and timestamp per transition. Bidirectional sync back to Azure Monitor alert state is via the Azure Monitor REST API (`PATCH /alerts/{alertId}`) called by the API gateway when state transitions occur.

### Claude's Discretion
- Exact Fabric capacity SKU per environment (F2 for dev, F4 for prod — or a single SKU if cost is a concern)
- KQL `EnrichedAlerts` resource inventory join specifics (which resource inventory table, join key)
- Fabric User Data Function Python packaging (inline code vs. separate Python module uploaded to Fabric)
- Event Hub partition count per environment (DETECT-001 specifies Standard tier, 10 partitions for prod; dev can be lower)
- Activity Log export pipeline specifics (diagnostic settings → Log Analytics workspace already from Phase 2 monitoring module; OneLake mirror is additive)
- Exact `classify_domain()` KQL function for Arc ambiguity edge cases beyond the resource_type mappings above

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Detection Plane Requirements
- `.planning/REQUIREMENTS.md` §DETECT — DETECT-001 through DETECT-007 define exact detection pipeline requirements
- `.planning/REQUIREMENTS.md` §INFRA — INFRA-007: Terraform provisions Fabric capacity, Eventhouse, Activator, OneLake using `azapi`
- `.planning/REQUIREMENTS.md` §AUDIT — AUDIT-003: Activity Log exported to Log Analytics + mirrored to Fabric OneLake, ≥2 years retention
- `.planning/ROADMAP.md` §"Phase 4: Detection Plane" — 6 success criteria define Phase 4 acceptance tests (30-second alert latency, 60-second round-trip, dedup load test, state sync, suppression rules, OneLake KQL query)

### Technology Stack
- `CLAUDE.md` §"Real-Time Detection Plane (Fabric)" — Fabric Eventhouse (GA), Activator (GA), Eventstreams (GA), Fabric IQ (Preview — keep off critical path); Event Hub connector; KQL schema examples; Activator trigger pattern; Fabric User Data Function pattern
- `CLAUDE.md` §"Infrastructure as Code (Terraform)" — `azapi ~>2.9` required for Fabric resources; resource mapping table shows `azapi_resource` for Fabric Workspace, Eventhouse, Activator; `azurerm` for Event Hub
- `CLAUDE.md` §"Data Persistence" — Cosmos DB `azure-cosmos 4.x` for incidents container; ETag optimistic concurrency pattern

### Existing Implementation References
- `services/api-gateway/models.py` — `IncidentPayload` Pydantic model (DETECT-004 payload schema); already live — Fabric User Data Function must match this exact schema
- `agents/shared/budget.py` — ETag optimistic concurrency pattern in Cosmos DB (reference implementation for dedup layer 1)
- `terraform/modules/networking/main.tf` — `snet-reserved-1` (10.0.64.0/24) reserved subnet for Phase 4 Event Hub; extend don't recreate
- `terraform/envs/dev/main.tf` — Existing module composition pattern; Phase 4 adds `module "fabric"` and `module "eventhub"` following the same pattern

### Research Artifacts
- `.planning/research/ARCHITECTURE.md` — Detection plane architecture; Fabric pipeline design
- `.planning/research/SUMMARY.md` — Key architectural decisions including Fabric as detection plane rationale

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/api-gateway/` (main.py, models.py, auth.py, foundry.py) — fully operational `POST /api/v1/incidents` endpoint with Entra auth; Phase 4 adds a new Service Principal caller but does NOT modify the gateway code
- `agents/shared/budget.py` — `BudgetTracker` with ETag optimistic concurrency (`replace_item(... match_condition="IfMatch")`); same pattern for `incidents` container dedup writes
- `terraform/modules/` — 7 existing modules; Phase 4 adds `fabric/` and updates `networking/` to activate the reserved Event Hub subnet
- `.github/workflows/` — reusable docker-push workflow; Phase 4 CI extends with Terraform plan/apply for Fabric

### Established Patterns
- Terraform per-domain module: `terraform/modules/{domain}/` with `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`
- Environment consumption: `terraform/envs/{env}/main.tf` calls `module "fabric" { source = "../../modules/fabric" ... }`
- ETag optimistic concurrency for Cosmos DB: read → mutate → replace with `etag=record["_etag"], match_condition="IfMatch"` (from `budget.py`)
- Entra Bearer token auth: all callers to the API gateway use Entra Bearer tokens; Service Principal client credentials flow is the standard approach for non-interactive callers (Fabric User Data Function)
- Tagging convention: all Terraform resources tagged `environment`, `managed-by: terraform`, `project: aap`

### Integration Points
- `terraform/modules/networking/main.tf` — activate `snet-reserved-1` for Event Hub VNet service endpoint
- `terraform/envs/*/main.tf` — add `module "fabric"` and `module "eventhub"` entries (all 3 environments)
- `services/api-gateway/auth.py` — existing Entra token validation; Fabric Service Principal Bearer token will pass through this unchanged
- Cosmos DB `incidents` container — new container (currently `sessions` and the two Phase 2 containers exist); `resource_id` partition key

</code_context>

<specifics>
## Specific Ideas

- **No Fabric IQ on the critical path.** CLAUDE.md explicitly notes Fabric IQ / Operations Agent is Preview. Phase 4 uses only GA components: Eventhouse + Activator + Eventstreams. Fabric IQ is explicitly excluded.
- **Activator fires on `domain != null` rows only.** The success criteria in ROADMAP.md §Phase 4 SC-1 confirms this: Activator triggers on `DetectionResults` rows where `domain` has a non-null value. The `sre` fallback domain (D-06) counts as non-null and will trigger the SRE agent thread.
- **Arc resource_type disambiguation:** `Microsoft.HybridCompute/machines` → `arc`; `Microsoft.Kubernetes/connectedClusters` → `arc`; regular VMs on Arc-managed subscriptions may need the resource tag `arc-managed: true` to distinguish from native Azure VMs → this is a Claude's Discretion edge case in the KQL function.

</specifics>

<deferred>
## Deferred Ideas

- **Fabric IQ semantic layer** — Fabric IQ (Operations Agent, ontology) is Preview and explicitly kept off the critical path per CLAUDE.md. Revisit in Phase 7 or v2 once GA.
- **Alert suppression rule management UI** — DETECT-007 requires suppressed alerts not to reach agents; the suppression rules themselves (Azure Monitor processing rules) are managed via the Azure portal or CLI, not via the AAP platform. A management UI for suppression rules is a v2 feature.
- **Event Hub consumer group isolation** — if multiple consumers need to read from the same Event Hub (e.g., both Eventhouse and a future audit pipeline), separate consumer groups are needed. Deferred to Phase 7 if a second consumer is added.
- **Fabric workspace managed identity for outbound calls** — noted as maturing; worth re-evaluating when GA if it eliminates the Service Principal secret rotation burden. Deferred.

</deferred>

---

*Phase: 04-detection-plane*
*Context gathered: 2026-03-26*
