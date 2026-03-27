# Phase 4: Detection Plane — Research

**Date:** 2026-03-26
**Scope:** INFRA-007, DETECT-001, DETECT-002, DETECT-003, DETECT-005, DETECT-006, DETECT-007, AUDIT-003
**Dependencies:** Phase 2 complete (API gateway `POST /api/v1/incidents` live), Phase 1 infrastructure (VNet, Cosmos DB, Key Vault)

---

## Technical Approach

### 1. Terraform Fabric Module (INFRA-007)

**Goal:** Single `terraform/modules/fabric/` module provisions all Fabric resources via `azapi` provider.

#### Provider Strategy

CLAUDE.md confirms Fabric resources have **no `azurerm` coverage** — `azapi ~>2.9` is required. A dedicated Microsoft Fabric Terraform provider (`microsoft/fabric`) exists in preview on the Terraform Registry, but CLAUDE.md explicitly specifies `azapi` for Fabric resources. We follow the project decision.

#### Resources to Provision

| Resource | azapi Type | API Version | Notes |
|---|---|---|---|
| Fabric Capacity | `Microsoft.Fabric/capacities` | `2023-11-01` (or latest GA) | F2 dev, F4 prod (D-01, D-02) |
| Fabric Workspace | `Microsoft.Fabric/workspaces` | Latest GA | Hosts Eventhouse, Activator, Lakehouse |
| Eventhouse | Fabric REST API item | Via `azapi_resource` or Fabric provider | KQL database for alert pipeline |
| KQL Database | Fabric REST API item | Created within Eventhouse | Hosts RawAlerts, EnrichedAlerts, DetectionResults |
| Activator | Fabric REST API item | Within workspace | Triggers on DetectionResults |
| OneLake Lakehouse | Fabric REST API item | Within workspace | Activity Log mirror, audit storage |

**Critical Implementation Detail:** Fabric workspace-level items (Eventhouse, KQL Database, Activator, Lakehouse) are managed through the **Fabric REST API** (`https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/...`), not standard ARM. Two approaches:

1. **Preferred: `azapi_resource`** with `type = "Microsoft.Fabric/workspaces/{itemType}"` — if the `azapi` provider supports Fabric data plane resources at the required API version.
2. **Fallback: `azapi_resource_action`** with custom REST calls to the Fabric API — more verbose but guaranteed to work since azapi can call any Azure REST endpoint.

**Naming Convention:** Follow the established pattern: `{resource}-aap-{environment}` (e.g., `eh-aap-dev` for Eventhouse, `fc-aap-dev` for Fabric capacity).

**Module Structure:**
```
terraform/modules/fabric/
  main.tf          # Fabric capacity + workspace + Eventhouse + KQL DB + Activator + Lakehouse
  variables.tf     # Environment-specific: SKU, location, capacity size
  outputs.tf       # eventhouse_uri, kql_database_name, workspace_id, activator_id
  versions.tf      # azapi ~>2.9
```

**Environment Composition (D-01):** Added to `terraform/envs/{dev,staging,prod}/main.tf` as:
```hcl
module "fabric" {
  source = "../../modules/fabric"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  fabric_capacity_sku = var.fabric_capacity_sku  # "F2" for dev, "F4" for prod
}
```

### 2. Event Hub Ingest Layer (DETECT-001)

**Goal:** Azure Event Hub as the single ingest point for all Azure Monitor alerts.

#### Terraform Resources (azurerm)

New module `terraform/modules/eventhub/` or extend `terraform/modules/monitoring/`:

| Resource | Terraform Type | Notes |
|---|---|---|
| Event Hub Namespace | `azurerm_eventhub_namespace` | Standard tier, auto-inflate optional |
| Event Hub | `azurerm_eventhub` | `raw-alerts`, partition_count=10 prod / 2 dev |
| Consumer Group | `azurerm_eventhub_consumer_group` | Dedicated for Eventhouse ingestion |
| Authorization Rule | `azurerm_eventhub_namespace_authorization_rule` | Send for Action Groups, Listen for Eventhouse |
| VNet Service Endpoint | Activate `snet-reserved-1` (D-03) | Extend `networking/main.tf` |
| Private DNS Zone | `privatelink.servicebus.windows.net` | Add to networking module |

**Decision: Extend monitoring module vs. new module.** Since the monitoring module already owns Log Analytics and App Insights, and Event Hub is a monitoring infrastructure component, the cleaner approach is a **new `terraform/modules/eventhub/` module** — keeping it separate preserves the per-domain module pattern (D-01 from Phase 1 decisions).

#### Networking Integration (D-03)

The `snet-reserved-1` subnet (10.0.64.0/24) was pre-allocated in Phase 1 for exactly this purpose. Implementation:

1. **Add VNet service endpoint** to `snet-reserved-1`: `service_endpoints = ["Microsoft.EventHub"]` in `networking/main.tf`.
2. **Add NSG** for the reserved subnet: allow inbound from VNet, outbound to Azure services.
3. **Add private DNS zone** for Event Hub: `privatelink.servicebus.windows.net`.
4. **Private endpoint** for Event Hub namespace in the centralized `private-endpoints` module.

#### Action Group Configuration

Azure Monitor Action Groups on all in-scope subscriptions must be configured to forward alerts to the Event Hub. This involves:

1. **`azurerm_monitor_action_group`** with `event_hub_receiver` block per subscription.
2. **`use_common_alert_schema = true`** — essential for consistent payload structure in KQL processing.
3. **Multi-subscription deployment:** Use `for_each` over subscription IDs or Azure Policy (`DeployIfNotExists`) to auto-create diagnostic settings.

**Recommended approach for multi-subscription:** Azure Policy with `DeployIfNotExists` effect that auto-creates Action Groups pointing to the central Event Hub. This is more scalable than managing Action Groups per-subscription in Terraform.

### 3. KQL Pipeline: RawAlerts -> EnrichedAlerts -> DetectionResults (DETECT-002)

**Goal:** Three-table enrichment pipeline in Eventhouse using KQL update policies (D-04).

#### Table Schema

**RawAlerts** (landing table from Event Hub):
```kql
.create table RawAlerts (
    alert_id: string,
    alert_name: string,
    severity: string,
    status: string,
    fired_at: datetime,
    resource_id: string,
    resource_type: string,
    subscription_id: string,
    resource_group: string,
    signal_type: string,
    alert_rule: string,
    description: string,
    raw_payload: dynamic,
    ingestion_time: datetime
)
```

**EnrichedAlerts** (resource inventory join):
```kql
.create table EnrichedAlerts (
    alert_id: string,
    alert_name: string,
    severity: string,
    fired_at: datetime,
    resource_id: string,
    resource_type: string,
    subscription_id: string,
    resource_group: string,
    resource_name: string,
    resource_location: string,
    resource_tags: dynamic,
    alert_rule: string,
    description: string,
    signal_type: string,
    ingestion_time: datetime
)
```

**DetectionResults** (classified, ready for Activator):
```kql
.create table DetectionResults (
    alert_id: string,
    severity: string,
    domain: string,
    fired_at: datetime,
    resource_id: string,
    resource_type: string,
    subscription_id: string,
    resource_name: string,
    alert_rule: string,
    description: string,
    kql_evidence: string,
    classified_at: datetime
)
```

#### classify_domain() Function (D-05, D-06)

```kql
.create-or-alter function classify_domain(resource_type: string) {
    case(
        resource_type has_any ("Microsoft.Compute/virtualMachines", "Microsoft.Compute/virtualMachineScaleSets",
                               "Microsoft.Batch/batchAccounts", "Microsoft.Compute/disks"), "compute",
        resource_type has_any ("Microsoft.Network/virtualNetworks", "Microsoft.Network/networkSecurityGroups",
                               "Microsoft.Network/loadBalancers", "Microsoft.Network/applicationGateways",
                               "Microsoft.Network/azureFirewalls", "Microsoft.Network/publicIPAddresses"), "network",
        resource_type has_any ("Microsoft.Storage/storageAccounts", "Microsoft.Storage/fileServices",
                               "Microsoft.Storage/blobServices"), "storage",
        resource_type has_any ("Microsoft.KeyVault/vaults", "Microsoft.Security",
                               "Microsoft.Sentinel"), "security",
        resource_type has_any ("Microsoft.HybridCompute/machines", "Microsoft.Kubernetes/connectedClusters",
                               "Microsoft.AzureArcData"), "arc",
        "sre"  // D-06: fallback to SRE agent for unclassifiable
    )
}
```

#### Update Policies (Chained)

**RawAlerts -> EnrichedAlerts:**
```kql
.create-or-alter function EnrichAlerts() {
    RawAlerts
    | extend resource_name = extract("/providers/[^/]+/[^/]+/(.+)$", 1, resource_id)
    | extend resource_location = ""   // populated from resource inventory if available
    | extend resource_tags = dynamic({})
    | project alert_id, alert_name, severity, fired_at, resource_id, resource_type,
              subscription_id, resource_group, resource_name, resource_location,
              resource_tags, alert_rule, description, signal_type, ingestion_time
}

.alter table EnrichedAlerts policy update
@'[{"IsEnabled": true, "Source": "RawAlerts", "Query": "EnrichAlerts()", "IsTransactional": true, "PropagateIngestionProperties": true}]'
```

**EnrichedAlerts -> DetectionResults:**
```kql
.create-or-alter function ClassifyAlerts() {
    EnrichedAlerts
    | extend domain = classify_domain(resource_type)
    | where isnotempty(domain)  // Always true due to SRE fallback
    | extend kql_evidence = strcat("Alert: ", alert_name, " on ", resource_id,
                                    " (", severity, ") at ", fired_at)
    | extend classified_at = now()
    | project alert_id, severity, domain, fired_at, resource_id, resource_type,
              subscription_id, resource_name, alert_rule, description,
              kql_evidence, classified_at
}

.alter table DetectionResults policy update
@'[{"IsEnabled": true, "Source": "EnrichedAlerts", "Query": "ClassifyAlerts()", "IsTransactional": true, "PropagateIngestionProperties": true}]'
```

**Performance notes:**
- Max update policy chain depth is 3 levels; this uses 2 (safe).
- `IsTransactional: true` ensures consistency — if enrichment fails, the raw record is also rolled back.
- Set a short retention policy on `RawAlerts` (e.g., 7 days) since enriched data is preserved downstream.

#### Resource Inventory Join (D-05 note)

The `EnrichAlerts()` function should ideally join with a resource inventory table (`ResourceInventory`) that is periodically refreshed via Azure Resource Graph queries. For MVP, the function extracts resource metadata from the alert payload itself (resource_id parsing). A full resource inventory materialized table is a Phase 5+ enhancement.

### 4. Activator -> User Data Function -> API Gateway (DETECT-003)

**Goal:** Fabric Activator triggers on new `DetectionResults` rows, calling a Fabric User Data Function that POSTs to the API gateway.

#### Activator Configuration

1. **Data source:** Eventhouse `DetectionResults` table.
2. **Trigger condition:** New row where `domain IS NOT NULL` (D-06 guarantees `sre` fallback so all rows qualify).
3. **Action:** Invoke Fabric User Data Function.

#### Fabric User Data Function (D-07, D-08)

A Python function deployed to Fabric that:
1. Receives the `DetectionResults` row from Activator.
2. Formats it into the `IncidentPayload` Pydantic model schema (matching `services/api-gateway/models.py` exactly).
3. Authenticates via Service Principal client credentials flow (D-08).
4. POSTs to `POST /api/v1/incidents` on the API gateway Container App.

**Payload mapping (DetectionResults -> IncidentPayload):**

| DetectionResults field | IncidentPayload field | Transformation |
|---|---|---|
| `alert_id` | `incident_id` | Direct map (prefixed with `det-` for traceability) |
| `severity` | `severity` | Direct map (`Sev0`-`Sev3`) |
| `domain` | `domain` | Direct map |
| `resource_id` | `affected_resources[0].resource_id` | Wrap in list |
| `subscription_id` | `affected_resources[0].subscription_id` | Direct map |
| `resource_type` | `affected_resources[0].resource_type` | Direct map |
| `alert_rule` | `detection_rule` | Direct map |
| `kql_evidence` | `kql_evidence` | Direct map |
| `description` | `description` | Direct map |
| `alert_rule` + `resource_name` | `title` | Concatenate for human-readable title |

#### Service Principal Authentication (D-08, D-09)

1. **Terraform provisions** an Entra app registration via `azuread` provider for the Fabric integration.
2. **Client credentials** (`client_id` + `client_secret`) stored in Key Vault (already provisioned in Phase 1).
3. **Gateway Entra app registration** (from Phase 2) adds an `incidents.write` application role.
4. **The Fabric SP is granted** the `incidents.write` role on the gateway app registration.
5. **At runtime,** the User Data Function acquires a token using MSAL `ConfidentialClientApplication` and passes it as `Authorization: Bearer <token>`.

### 5. Alert Deduplication (DETECT-005)

**Goal:** Two-layer dedup preventing duplicate agent threads.

#### Layer 1: Time-Window Collapse (D-11)

Multiple alerts for the same `resource_id` + `detection_rule` within a 5-minute window collapse into a single Cosmos DB incident record.

**Implementation in the incident ingestion service (new `services/detection/dedup.py`):**

```python
async def dedup_layer1(incident: IncidentPayload, container: ContainerProxy) -> tuple[bool, dict]:
    """Check for existing incident with same resource_id + detection_rule within 5 minutes.

    Returns:
        (is_duplicate, existing_record_or_none)
    """
    window_start = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    query = """
        SELECT * FROM incidents c
        WHERE c.resource_id = @resource_id
          AND c.detection_rule = @detection_rule
          AND c.created_at >= @window_start
          AND c.status != 'closed'
        ORDER BY c.created_at DESC
        OFFSET 0 LIMIT 1
    """
    params = [
        {"name": "@resource_id", "value": incident.affected_resources[0].resource_id},
        {"name": "@detection_rule", "value": incident.detection_rule},
        {"name": "@window_start", "value": window_start},
    ]

    results = list(container.query_items(query=query, parameters=params,
                                          partition_key=incident.affected_resources[0].resource_id))

    if results:
        return True, results[0]
    return False, None
```

**ETag Optimistic Concurrency:** When collapsing duplicates, use the same pattern from `agents/shared/budget.py`:
- Read existing record.
- Increment `duplicate_count` field.
- `replace_item(..., etag=record["_etag"], match_condition="IfMatch")`.
- On `412 Precondition Failed`, retry with fresh read.

#### Layer 2: Open-Incident Correlation (D-12)

When a new **distinct** alert arrives for a `resource_id` that already has an open incident, the alert is appended to the existing incident's `correlated_alerts` array.

```python
async def dedup_layer2(incident: IncidentPayload, container: ContainerProxy) -> tuple[bool, dict]:
    """Check for any open incident for the same resource_id."""
    query = """
        SELECT * FROM incidents c
        WHERE c.resource_id = @resource_id
          AND c.status IN ('new', 'acknowledged')
        ORDER BY c.created_at DESC
        OFFSET 0 LIMIT 1
    """
    params = [{"name": "@resource_id", "value": incident.affected_resources[0].resource_id}]

    results = list(container.query_items(query=query, parameters=params,
                                          partition_key=incident.affected_resources[0].resource_id))

    if results:
        existing = results[0]
        # Append new alert to correlated_alerts array
        new_correlated = [*existing.get("correlated_alerts", []), {
            "alert_id": incident.incident_id,
            "severity": incident.severity,
            "detection_rule": incident.detection_rule,
            "correlated_at": datetime.now(timezone.utc).isoformat(),
        }]
        updated = {**existing, "correlated_alerts": new_correlated,
                   "updated_at": datetime.now(timezone.utc).isoformat()}
        container.replace_item(item=existing["id"], body=updated,
                               etag=existing["_etag"], match_condition="IfMatch")
        return True, updated
    return False, None
```

**Execution order:** Layer 1 (time-window collapse) runs first. If not a time-window duplicate, Layer 2 (open-incident correlation) runs. If neither matches, a new incident record is created.

**Where this logic lives:** This dedup logic executes in the API gateway's `POST /api/v1/incidents` handler — **before** creating a Foundry thread. The gateway's `main.py` is extended with a dedup check. This keeps the gateway thin (it's just a conditional check before dispatch) while preventing duplicate threads.

### 6. Alert State Lifecycle (DETECT-006)

**Goal:** Bidirectional sync of alert states between Cosmos DB and Azure Monitor.

#### Cosmos DB State Model (D-13, D-14)

The `incidents` container already exists (Phase 1) with `partition_key: /resource_id`. The schema from D-13 in the CONTEXT document defines the structure. State transitions are tracked in `status_history` array.

**State Machine:**
```
new -> acknowledged -> closed
new -> closed (direct close)
```

Each transition records `{status, actor, timestamp}` in `status_history`.

#### Bidirectional Azure Monitor Sync (D-14)

When an alert state transitions in the platform:

```python
async def sync_alert_state_to_azure_monitor(
    alert_id: str,
    new_state: str,  # "Acknowledged" | "Closed"
    subscription_id: str,
    credential: DefaultAzureCredential,
):
    """PATCH the Azure Monitor alert state back to Azure."""
    from azure.mgmt.alertsmanagement import AlertsManagementClient

    client = AlertsManagementClient(credential, subscription_id)
    client.alerts.change_state(
        alert_id=alert_id,
        new_state=new_state,  # Maps: acknowledged -> Acknowledged, closed -> Closed
    )
```

**API:** `PATCH /subscriptions/{sub}/providers/Microsoft.AlertsManagement/alerts/{alertId}?api-version=2019-05-05-preview` — changes the user-facing alert state (`New` / `Acknowledged` / `Closed`). Note: the `monitor_condition` (`Fired`/`Resolved`) is controlled by Azure Monitor itself and cannot be changed via API.

**Implementation location:** New `services/detection/alert_sync.py` module. Called from the API gateway when an operator or agent transitions an incident's status. The sync is fire-and-forget with error logging (Azure Monitor state sync failure should not block the platform state transition).

### 7. Alert Suppression Rules (DETECT-007)

**Goal:** Azure Monitor processing rules that suppress alerts are respected — suppressed alerts never reach agents.

#### How It Works

Azure Monitor **processing rules** (formerly "action rules") can suppress alerts before they trigger Action Groups. If a processing rule suppresses an alert class:

1. The alert fires but the Action Group is **not invoked**.
2. The alert **never reaches Event Hub** because the action (Event Hub send) is suppressed.
3. Therefore, it **never enters `RawAlerts`**, `EnrichedAlerts`, or `DetectionResults`.

**This is inherent behavior** — no code required in the detection plane. The key insight is that suppression happens at the Azure Monitor Action Group level, upstream of Event Hub.

#### Verification Strategy

To validate DETECT-007:
1. Create an Azure Monitor processing rule suppressing a specific alert class.
2. Fire a matching alert.
3. Assert no record appears in `DetectionResults` and no Cosmos DB incident is created.
4. Remove the suppression rule.
5. Fire the same alert again.
6. Assert the alert flows through the full pipeline.

### 8. Activity Log Export to OneLake (AUDIT-003)

**Goal:** Azure Activity Log from all subscriptions exported to Log Analytics and mirrored to Fabric OneLake with >=2 years retention.

#### Step 1: Activity Log -> Log Analytics

Use `azurerm_monitor_diagnostic_setting` at the subscription level:

```hcl
resource "azurerm_monitor_diagnostic_setting" "activity_log" {
  for_each = toset(var.subscription_ids)

  name                       = "aap-activity-log-export"
  target_resource_id         = "/subscriptions/${each.value}"
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "Administrative" }
  enabled_log { category = "Security" }
  enabled_log { category = "ServiceHealth" }
  enabled_log { category = "Alert" }
  enabled_log { category = "Recommendation" }
  enabled_log { category = "Policy" }
  enabled_log { category = "Autoscale" }
  enabled_log { category = "ResourceHealth" }
}
```

**Multi-subscription:** Requires provider aliases or Azure Policy (`DeployIfNotExists`). Given the project uses `for_each` over subscription IDs in the RBAC module (Phase 2 pattern), the same pattern works here.

#### Step 2: Log Analytics -> OneLake Mirror

Fabric OneLake supports **data shortcuts** to Log Analytics workspaces. Alternatively, use Fabric Eventstreams to continuously stream from Log Analytics to OneLake.

**Recommended approach for >=2 years retention:**
1. **Fabric Lakehouse** in the same workspace as Eventhouse.
2. **OneLake shortcut** pointing to the Log Analytics workspace, or a **Fabric Data Pipeline** that runs on a schedule (e.g., hourly) to export Activity Log records from Log Analytics to OneLake in Parquet format.
3. **OneLake retention policy** set to 730 days minimum.

#### Step 3: Validation

KQL query against OneLake `ActivityLog` table should return events within 5 minutes of source event (SC-6):
```kql
ActivityLog
| where TimeGenerated > ago(5m)
| where SubscriptionId in (scope_subscriptions)
| take 10
```

---

## Validation Architecture

### Unit Tests

#### 1. KQL classify_domain() Function Tests

**Location:** `tests/detection/test_classify_domain.py`
**Approach:** Since KQL functions can't be unit-tested natively in Python, test the domain classification logic as a Python mirror function that must produce identical results to the KQL version.

| Test Case | Input `resource_type` | Expected `domain` |
|---|---|---|
| VM | `Microsoft.Compute/virtualMachines` | `compute` |
| VMSS | `Microsoft.Compute/virtualMachineScaleSets` | `compute` |
| NSG | `Microsoft.Network/networkSecurityGroups` | `network` |
| Storage Account | `Microsoft.Storage/storageAccounts` | `storage` |
| Key Vault | `Microsoft.KeyVault/vaults` | `security` |
| Arc Server | `Microsoft.HybridCompute/machines` | `arc` |
| Arc K8s | `Microsoft.Kubernetes/connectedClusters` | `arc` |
| Unknown | `Microsoft.ContainerService/managedClusters` | `sre` |
| Empty string | `` | `sre` |
| Case variation | `microsoft.compute/virtualMachines` | `compute` |

#### 2. Deduplication Logic Tests

**Location:** `tests/detection/test_dedup.py`
**Mocking:** Mock Cosmos DB `ContainerProxy` (same pattern as `tests/agents/test_budget.py`)

| Test Scenario | Expected Behavior |
|---|---|
| First alert for resource | Creates new incident, returns `is_duplicate=False` |
| Same alert within 5-min window | Layer 1 collapse: `is_duplicate=True`, `duplicate_count` incremented |
| Different alert, same resource, open incident | Layer 2 correlation: added to `correlated_alerts` array |
| Same resource, closed incident | New incident created (not correlated to closed) |
| ETag conflict on dedup write | Retries with fresh read (test 412 handling) |
| 10 identical alerts in 5-min window | All collapse into 1 incident (SC-3) |

#### 3. IncidentPayload Mapping Tests

**Location:** `tests/detection/test_payload_mapping.py`

| Test Case | Validates |
|---|---|
| Valid DetectionResults row maps to valid IncidentPayload | All fields correctly mapped |
| Severity mapping (Sev0-Sev3) | Regex validation passes |
| Domain mapping (all 6 domains) | Enum validation passes |
| Missing optional fields handled | `kql_evidence=None` OK |
| Invalid resource_id rejected | Pydantic validation error |

#### 4. Alert State Lifecycle Tests

**Location:** `tests/detection/test_alert_state.py`

| Test Case | Validates |
|---|---|
| new -> acknowledged | Valid transition, status_history updated |
| new -> closed | Valid transition |
| acknowledged -> closed | Valid transition |
| closed -> new | Invalid (rejected) |
| Transition records actor and timestamp | status_history entry correct |
| Azure Monitor sync called on transition | Mock REST API called with correct state |
| Azure Monitor sync failure is non-blocking | Transition succeeds, error logged |

### Integration Tests

#### 5. Event Hub -> Eventhouse Pipeline Test

**Location:** `tests/integration/test_detection_pipeline.py`
**Marks:** `@pytest.mark.integration` (excluded from fast CI, per Phase 3 precedent)

1. **Send synthetic alert** to Event Hub using `azure.eventhub.EventHubProducerClient` with Common Alert Schema payload.
2. **Wait up to 30 seconds** (SC-1 SLA).
3. **Query Eventhouse** `RawAlerts` table via KQL to confirm arrival.
4. **Query `EnrichedAlerts`** to confirm update policy fired.
5. **Query `DetectionResults`** to confirm `domain IS NOT NULL`.

#### 6. Full Round-Trip Test (SC-2)

**Location:** `tests/integration/test_round_trip.py`

1. Fire a synthetic Azure Monitor alert.
2. Verify `DetectionResults` row within 30 seconds.
3. Verify `POST /api/v1/incidents` call received by API gateway (mock or real).
4. Verify Cosmos DB incident record created.
5. **Total time < 60 seconds** (SC-2 SLA measured via timestamps).

#### 7. Dedup Load Test (SC-3)

**Location:** `tests/integration/test_dedup_load.py`

1. Fire 10 identical alerts (same `resource_id`, same rule) within a 1-minute burst.
2. Wait for pipeline processing (30 seconds per SC-1 SLA, plus buffer).
3. Query Cosmos DB: exactly 1 incident record with `duplicate_count >= 9`.
4. Fire a distinct alert for the same `resource_id`.
5. Verify it's correlated (added to `correlated_alerts` array, no new thread).

### E2E / System Tests

#### 8. Alert Suppression Test (SC-5)

1. Create Azure Monitor processing rule suppressing a specific alert class via ARM API.
2. Fire matching alert.
3. Wait 60 seconds.
4. Assert: no `DetectionResults` row, no Cosmos DB incident.
5. Remove suppression rule.
6. Fire same alert.
7. Assert: `DetectionResults` row exists, Cosmos DB incident created.

#### 9. Alert State Bidirectional Sync Test (SC-4)

1. Fire alert -> creates incident in Cosmos DB.
2. Transition Cosmos DB status to `acknowledged`.
3. Query Azure Monitor alert state via ARM API -> expect `Acknowledged`.
4. Transition Cosmos DB status to `closed`.
5. Query Azure Monitor alert state -> expect `Closed`.

#### 10. Activity Log OneLake Test (SC-6)

1. Trigger a known Activity Log event (e.g., create a temporary resource group).
2. Wait 5 minutes.
3. Query OneLake `ActivityLog` table for the event.
4. Assert event present with correct timestamp.

### Terraform Validation

#### 11. `terraform plan` Validation

- `terraform plan` on dev environment succeeds with new `fabric` and `eventhub` modules.
- No unexpected changes to existing resources.
- All new resources tagged correctly.

#### 12. `terraform apply` Validation

- `terraform apply` creates all Fabric and Event Hub resources without error.
- Post-apply: `terraform plan` shows zero changes (idempotent).

### Performance Validation

#### 13. Latency Benchmarks

| Metric | SLA | Measurement Method |
|---|---|---|
| Alert fire -> `RawAlerts` table | < 30 seconds | Timestamp comparison: Azure Monitor fire time vs. Eventhouse ingestion_time |
| Alert fire -> Orchestrator thread | < 60 seconds | OpenTelemetry trace timestamps: first span to Foundry thread creation |
| Dedup query latency | < 100ms p99 | Cosmos DB metrics on `incidents` container cross-partition query |
| Activity Log -> OneLake | < 5 minutes | Timestamp comparison: Activity Log TimeGenerated vs. OneLake record |

---

## Implementation Risks

### Risk 1: Fabric Terraform Provider Maturity (HIGH)

**Problem:** Fabric resources managed via `azapi` may have limited documentation and unstable API versions. The dedicated `microsoft/fabric` Terraform provider is in preview.

**Mitigation:**
- Pin `azapi` version to `~>2.9` as specified in CLAUDE.md.
- Use `azapi_resource` with explicit API versions documented in the Fabric REST API reference.
- If `azapi` cannot manage Fabric workspace items (Eventhouse, Activator, Lakehouse), fall back to:
  - `null_resource` with `local-exec` provisioners calling the Fabric REST API via `curl`/`az rest`.
  - Or the `microsoft/fabric` provider if it covers needed resources.
- Write comprehensive `terraform plan` tests to detect API version drift.

### Risk 2: Eventhouse Event Hub Connector Configuration (MEDIUM)

**Problem:** The Event Hub -> Eventhouse streaming connector may require manual configuration through the Fabric portal (not fully Terraform-automatable).

**Mitigation:**
- Research if the Fabric REST API supports creating data connections programmatically (`POST /v1/workspaces/{id}/eventhouses/{id}/dataConnections`).
- If not Terraform-automatable, document the manual setup step and provide a setup script.
- Test connector reliability with sustained alert volumes.

### Risk 3: Activator -> User Data Function Latency (MEDIUM)

**Problem:** The Activator trigger + User Data Function execution + REST POST chain might exceed the 60-second round-trip SLA (SC-2).

**Mitigation:**
- Measure Activator trigger latency independently.
- Keep User Data Function lightweight (no heavy processing — just payload formatting and HTTP POST).
- If Activator latency is too high, consider:
  - Direct Eventstream -> Azure Function path (bypassing Activator).
  - Eventhouse `.export` continuous export to a webhook.

### Risk 4: Cosmos DB Cross-Partition Query for Dedup Layer 2 (MEDIUM)

**Problem:** Layer 2 dedup queries `incidents` container by `resource_id` (which is the partition key), so queries are efficient within a partition. However, if the dedup query needs to scan across partitions (e.g., searching by `status` alone), performance degrades.

**Mitigation:**
- D-10 decision already addresses this: partition key is `resource_id`, so both dedup queries are partition-scoped (always filter by `resource_id`).
- Add composite index on `(resource_id, status, created_at)` for efficient dedup queries.
- Monitor Cosmos DB RU consumption during load tests.

### Risk 5: Multi-Subscription Action Group Deployment (LOW)

**Problem:** Creating Action Groups across multiple subscriptions requires either multi-provider Terraform configuration or Azure Policy.

**Mitigation:**
- Use Azure Policy (`DeployIfNotExists`) for scalable multi-subscription deployment.
- For dev/staging (single subscription), direct Terraform is sufficient.
- Document the Azure Policy approach for prod multi-subscription deployment.

### Risk 6: KQL Update Policy Failure Mode (MEDIUM)

**Problem:** If a KQL update policy function fails (e.g., `classify_domain()` encounters unexpected input), and `IsTransactional: true` is set, the source ingestion also fails — potentially losing alerts.

**Mitigation:**
- `classify_domain()` has an explicit `sre` fallback for all unrecognized resource types (D-06), preventing NULL domain classification failures.
- The `EnrichAlerts()` function uses defensive `extract()` and `coalesce()` patterns.
- Consider setting `IsTransactional: false` on the first hop (RawAlerts -> EnrichedAlerts) so raw data is never lost, while keeping `true` on the second hop (EnrichedAlerts -> DetectionResults) for consistency.
- Set up Eventhouse ingestion failure monitoring via `.show ingestion failures`.

### Risk 7: Service Principal Secret Rotation (LOW)

**Problem:** The Fabric User Data Function uses a Service Principal with `client_secret` stored in Key Vault (D-08). Secrets expire and must be rotated.

**Mitigation:**
- Set Key Vault secret expiration alert (e.g., 30 days before expiry).
- Document rotation procedure.
- Consider using certificate-based authentication instead of client secrets for longer rotation intervals.
- Deferred concern: Fabric workspace managed identity (noted in CONTEXT deferred items) would eliminate this.

---

## Key Dependencies

### Hard Dependencies (Must Exist Before Phase 4)

| Dependency | Source Phase | What's Needed | Status |
|---|---|---|---|
| API Gateway `POST /api/v1/incidents` | Phase 2 | Live endpoint accepting `IncidentPayload` | Done |
| Entra Bearer token validation | Phase 2 | Gateway validates Entra tokens; new Service Principal must be recognized | Done |
| Cosmos DB `incidents` container | Phase 1 | Container with `partition_key: /resource_id` | Done |
| Cosmos DB `sessions` container | Phase 1 | Budget tracking for agent sessions | Done |
| Key Vault | Phase 1 | Store Fabric SP client_secret | Done |
| VNet + `snet-reserved-1` subnet | Phase 1 | Pre-allocated for Event Hub networking | Done |
| Log Analytics Workspace | Phase 1 | Activity Log export destination | Done |
| ETag optimistic concurrency pattern | Phase 2 | `agents/shared/budget.py` as reference implementation | Done |
| Terraform CI workflow | Phase 1 | `terraform plan` on PR, `terraform apply` on merge | Done |

### Soft Dependencies (Nice to Have)

| Dependency | Source | Notes |
|---|---|---|
| Resource inventory table in Eventhouse | Future | For richer `EnrichedAlerts` join; MVP uses alert payload data |
| Fabric workspace managed identity | Preview | Would replace Service Principal secret; deferred |
| Microsoft Fabric Terraform provider | Preview | Would simplify Fabric provisioning; `azapi` works today |

### External Services Required

| Service | Purpose | Provisioning |
|---|---|---|
| Azure Fabric Capacity | Compute for Eventhouse + Activator | Terraform `azapi_resource` |
| Azure Event Hub Namespace (Standard) | Alert ingest | Terraform `azurerm_eventhub_namespace` |
| Azure Monitor Action Groups | Alert forwarding | Terraform `azurerm_monitor_action_group` or Azure Policy |
| Entra App Registration (Fabric SP) | User Data Function auth | Terraform `azuread_application` |

### Files Modified (Existing)

| File | Change | Reason |
|---|---|---|
| `terraform/modules/networking/main.tf` | Add service endpoint + NSG to `snet-reserved-1` | D-03: Event Hub VNet integration |
| `terraform/modules/networking/outputs.tf` | Export `subnet_reserved_1_id` | Needed by eventhub module |
| `terraform/modules/networking/variables.tf` | No changes (CIDR already defined) | -- |
| `terraform/envs/dev/main.tf` | Add `module "fabric"` + `module "eventhub"` | Module composition |
| `terraform/envs/staging/main.tf` | Add `module "fabric"` + `module "eventhub"` | Module composition |
| `terraform/envs/prod/main.tf` | Add `module "fabric"` + `module "eventhub"` | Module composition |
| `services/api-gateway/main.py` | Add dedup check before Foundry dispatch | DETECT-005 |
| `terraform/modules/databases/cosmos.tf` | Add composite index to `incidents` container | Dedup query performance |

### New Files Created

| File | Purpose |
|---|---|
| `terraform/modules/fabric/` (main.tf, variables.tf, outputs.tf, versions.tf) | Fabric capacity, workspace, Eventhouse, Activator, Lakehouse |
| `terraform/modules/eventhub/` (main.tf, variables.tf, outputs.tf, versions.tf) | Event Hub namespace, hub, consumer groups, auth rules |
| `services/detection/dedup.py` | Two-layer deduplication logic |
| `services/detection/alert_sync.py` | Bidirectional Azure Monitor alert state sync |
| `services/detection/payload_mapper.py` | DetectionResults -> IncidentPayload mapping |
| `services/detection/__init__.py` | Package init |
| `fabric/kql/` (schemas, functions, policies) | KQL table schemas, classify_domain(), update policies |
| `fabric/user-data-function/` | Python User Data Function for Activator -> API Gateway |
| `tests/detection/` (unit tests) | test_classify_domain.py, test_dedup.py, test_payload_mapping.py, test_alert_state.py |
| `tests/integration/` (integration tests) | test_detection_pipeline.py, test_round_trip.py, test_dedup_load.py |

---

## RESEARCH COMPLETE
