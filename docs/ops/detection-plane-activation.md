# Detection Plane Activation Guide

> **Phase 21** activates the Fabric detection pipeline in production.
> Run `scripts/ops/21-2-activate-detection-plane.sh` for the interactive guided procedure.

---

## Overview

The Fabric detection pipeline was designed in **Phase 4** and the infrastructure is fully managed by Terraform in `terraform/modules/fabric/`. The pipeline ingests live Azure Monitor alerts and routes classified incidents to the AI agent platform automatically — no simulation scripts required after activation.

After `terraform apply` with `enable_fabric_data_plane = true` (Plan 21-1), three manual steps are required to complete the wiring:

1. **Eventstream connector** — connect Azure Event Hub to the Eventhouse (cannot be automated via Terraform or the Fabric REST API)
2. **Activator trigger** — configure the detection condition (`domain IS NOT NULL`) and action (invoke User Data Function)
3. **OneLake mirror** — configure Activity Log mirroring with ≥730 day retention (AUDIT-003 compliance)

---

## Prerequisites

| Requirement | How to verify |
|---|---|
| Phase 19 complete (all 5 plans applied) | `az containerapp list --resource-group rg-aap-prod -o table` shows all 12 containers |
| `terraform apply` on `terraform/envs/prod/` completed with `enable_fabric_data_plane = true` | `terraform output -chdir=terraform/envs/prod \| grep fabric` shows workspace/eventhouse IDs |
| Fabric capacity `fcaapprod` is active and has CU quota | Fabric portal → Capacity settings → check status = Active |
| Event Hub namespace `ehns-aap-prod` is provisioned and receiving Azure Monitor alerts | `az eventhubs namespace show --resource-group rg-aap-prod --name ehns-aap-prod` |
| API gateway `ca-api-gateway-prod` is healthy and accepting `POST /api/v1/incidents` | `curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health` |
| `az login` with active session on subscription `4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c` | `az account show` |

---

## Architecture

```
Azure Monitor Alerts
       |
       | (Action Group routes to Event Hub)
       v
Event Hub (ehns-aap-prod / eh-alerts-prod)
       |
       v  (Eventstream connector — manual step)
Eventhouse (eh-aap-prod)
  RawAlerts table
       |
       v  (KQL update policy — automatic)
  EnrichedAlerts table
       |
       v  (KQL classify_domain() function — automatic)
  DetectionResults table
       |
       v  (Activator trigger: new row WHERE domain IS NOT NULL)
Fabric Activator (act-aap-prod)
       |
       v  (User Data Function: handle_activator_trigger)
POST /api/v1/incidents
  ca-api-gateway-prod
       |
       v  (incident_id = "det-<alert_id>")
Orchestrator -> Domain Agent -> Triage
```

---

## Step-by-Step Procedure

Run the interactive runbook for guided execution with prompts and confirmation checks:

```bash
bash scripts/ops/21-2-activate-detection-plane.sh
```

The script walks through the following steps:

### Phase 0: Pre-flight Terraform Plan (run BEFORE `terraform apply`)

Verify the plan shows exactly 5 `azapi_resource` creates and 2 `null_resource` creates in `module.fabric`:

```bash
terraform -chdir=terraform/envs/prod plan \
  -var-file=credentials.tfvars \
  -target=module.fabric \
  -no-color 2>&1 | head -80
```

Expected creates:
- `azapi_resource.fabric_workspace[0]`
- `azapi_resource.fabric_eventhouse[0]`
- `azapi_resource.fabric_kql_database[0]`
- `azapi_resource.fabric_activator[0]`
- `azapi_resource.fabric_lakehouse[0]`
- `null_resource.activator_setup_reminder[0]`
- `null_resource.onelake_mirror_setup_reminder[0]`

> **Warning:** If more than 7 resources change in the fabric module, investigate before applying.

### Step 1: Verify Fabric Resources Provisioned

After `terraform apply`, all 5 resources must be in the `aap-prod` Fabric workspace:

| Resource | Name |
|---|---|
| Workspace | `aap-prod` |
| Eventhouse | `eh-aap-prod` |
| KQL Database | `kqldb-aap-prod` |
| Activator | `act-aap-prod` |
| Lakehouse | `lh-aap-prod` |

### Step 2: Eventstream Connector Setup

1. Open [Fabric portal](https://app.fabric.microsoft.com) → workspace `aap-prod`
2. **New → Eventstream** → name: `eventstream-alerts-prod`
3. **Source**: Azure Event Hub
   - Namespace: `ehns-aap-prod`
   - Event Hub: `eh-alerts-prod`
   - Connection string:
     ```bash
     az eventhubs namespace authorization-rule keys list \
       --resource-group rg-aap-prod \
       --namespace-name ehns-aap-prod \
       --name RootManageSharedAccessKey \
       --query primaryConnectionString -o tsv
     ```
4. **Destination**: Eventhouse → `kqldb-aap-prod` → table: `RawAlerts` → format: JSON
5. **Publish** the Eventstream to activate

### Step 3: KQL Table Schema Setup

In the Eventhouse query editor (`kqldb-aap-prod`), create the three tables:

```kql
.create table RawAlerts (
    alert_id: string,
    severity: string,
    fired_at: datetime,
    resource_id: string,
    resource_type: string,
    subscription_id: string,
    resource_name: string,
    alert_rule: string,
    description: string,
    kql_evidence: string,
    raw_payload: dynamic
)

.create table EnrichedAlerts (
    alert_id: string,
    severity: string,
    fired_at: datetime,
    resource_id: string,
    resource_type: string,
    subscription_id: string,
    resource_name: string,
    alert_rule: string,
    description: string,
    kql_evidence: string,
    domain: string,
    classified_at: datetime
)

.create table DetectionResults (
    alert_id: string,
    severity: string,
    fired_at: datetime,
    resource_id: string,
    resource_type: string,
    subscription_id: string,
    resource_name: string,
    alert_rule: string,
    description: string,
    kql_evidence: string,
    domain: string,
    classified_at: datetime
)
```

Then apply the KQL update policies from `services/detection-plane/kql/` (classify_domain function and update policies for RawAlerts → EnrichedAlerts → DetectionResults).

### Step 4: Activator Trigger Configuration

1. Open Activator `act-aap-prod` in workspace `aap-prod`
2. **Set data source**: Eventhouse → `eh-aap-prod` → `kqldb-aap-prod` → `DetectionResults`
3. **Trigger condition**: new row where `domain IS NOT NULL`
4. **Action**: User Data Function → `handle_activator_trigger`
5. **Save and activate**

> Reference: `terraform/modules/fabric/main.tf` → `null_resource.activator_setup_reminder`

### Step 5: OneLake Mirror Setup (AUDIT-003)

Configure Activity Log mirroring to `lh-aap-prod` with ≥730 day retention.

Full instructions: [`services/detection-plane/docs/AUDIT-003-onelake-setup.md`](../../services/detection-plane/docs/AUDIT-003-onelake-setup.md)

**Summary:**
1. Open Lakehouse `lh-aap-prod` → **Get data → New shortcut**
2. Source: Azure Data Lake Storage Gen2 → Log Analytics export storage → path `/AzureActivityLog/`
3. Set retention to 730 days (via table properties or Spark SQL)

### Step 6: Validation KQL Queries

Run these queries in the `kqldb-aap-prod` query editor to confirm the pipeline is live:

```kql
// Check RawAlerts table exists and has data
RawAlerts | count

// Check enrichment pipeline (last hour)
EnrichedAlerts
| where classified_at > ago(1h)
| count

// Check classification pipeline — sample classified results
DetectionResults
| where domain != ""
| take 5

// Pipeline health: alert volume by domain in last hour
DetectionResults
| where classified_at > ago(1h)
| summarize Count=count() by domain
| order by Count desc
```

### Step 7: End-to-End Smoke Test

1. Fire a test Azure Monitor alert
2. Wait 60 seconds
3. Query `DetectionResults | where fired_at > ago(5m) | take 1`
4. Verify incident created with `det-` prefix via API:
   ```bash
   curl -s \
     -H "Authorization: Bearer <token>" \
     "https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/incidents?limit=1"
   ```
   Expected: `incident_id` begins with `det-` (from `payload_mapper.py`)

---

## Domain Classification Reference

The `classify_domain()` function in `services/detection-plane/classify_domain.py` classifies ARM resource types to agent domains. The KQL function `fabric/kql/functions/classify_domain.kql` implements the same logic.

| Resource Type | Domain |
|---|---|
| `Microsoft.Compute/virtualMachines` | `compute` |
| `Microsoft.Compute/virtualMachineScaleSets` | `compute` |
| `Microsoft.Compute/disks` | `compute` |
| `Microsoft.Batch/batchAccounts` | `compute` |
| `Microsoft.Compute/availabilitySets` | `compute` |
| `Microsoft.Compute/images` | `compute` |
| `Microsoft.Network/virtualNetworks` | `network` |
| `Microsoft.Network/networkSecurityGroups` | `network` |
| `Microsoft.Network/loadBalancers` | `network` |
| `Microsoft.Network/applicationGateways` | `network` |
| `Microsoft.Network/azureFirewalls` | `network` |
| `Microsoft.Network/publicIPAddresses` | `network` |
| `Microsoft.Network/trafficManagerProfiles` | `network` |
| `Microsoft.Network/frontDoors` | `network` |
| `Microsoft.Network/dnsZones` | `network` |
| `Microsoft.Network/expressRouteCircuits` | `network` |
| `Microsoft.Network/vpnGateways` | `network` |
| `Microsoft.Storage/storageAccounts` | `storage` |
| `Microsoft.Storage/fileServices` | `storage` |
| `Microsoft.Storage/blobServices` | `storage` |
| `Microsoft.StorageSync/storageSyncServices` | `storage` |
| `Microsoft.KeyVault/vaults` | `security` |
| `Microsoft.Security/*` (prefix) | `security` |
| `Microsoft.Sentinel/*` (prefix) | `security` |
| `Microsoft.HybridCompute/machines` | `arc` |
| `Microsoft.Kubernetes/connectedClusters` | `arc` |
| `Microsoft.AzureArcData/*` (prefix) | `arc` |
| _(unrecognized types)_ | `sre` (fallback) |

Classification uses exact match first, then prefix match. Unrecognized types fall back to `sre` (Decision D-06).

---

## Troubleshooting

### Alerts not appearing in RawAlerts

**Symptoms:** `RawAlerts | count` returns 0 after alerts fire.

**Checks:**
1. Verify the Eventstream connector is in **Active** status in the Fabric portal
2. Check the Event Hub has messages: `az eventhubs eventhub show --resource-group rg-aap-prod --namespace-name ehns-aap-prod --name eh-alerts-prod`
3. Verify the connection string is valid: re-run the `az eventhubs namespace authorization-rule keys list` command
4. Check the data format — RawAlerts schema expects JSON with `alert_id`, `severity`, etc.
5. Verify Azure Monitor Action Groups are configured to route alerts to `eh-alerts-prod`

### Alerts not enriched (EnrichedAlerts empty)

**Symptoms:** `RawAlerts | count` > 0 but `EnrichedAlerts | count` = 0.

**Checks:**
1. Verify the KQL update policy is attached to `RawAlerts`:
   ```kql
   .show table RawAlerts policy update
   ```
2. Check the update policy function exists:
   ```kql
   .show function EnrichAlerts
   ```
3. Check for ingestion errors:
   ```kql
   .show ingestion failures | take 10
   ```

### DetectionResults has empty domain

**Symptoms:** `DetectionResults | where domain != "" | count` = 0 or very low.

**Checks:**
1. Verify the `classify_domain()` KQL function is deployed:
   ```kql
   .show function classify_domain
   ```
2. Check the `resource_type` values arriving in `RawAlerts` match expected ARM types (lowercase, no version suffix)
3. Confirm the update policy from `EnrichedAlerts` to `DetectionResults` is active:
   ```kql
   .show table EnrichedAlerts policy update
   ```
4. Review `classify_domain.py` for the canonical mapping — Python and KQL must produce identical results

### Activator not triggering

**Symptoms:** `DetectionResults` has data but no incidents arrive at `POST /api/v1/incidents`.

**Checks:**
1. Open Activator `act-aap-prod` in Fabric portal → verify status = **Active**
2. Check the trigger condition is exactly: `new row where domain IS NOT NULL`
3. Verify the User Data Function `handle_activator_trigger` is deployed and reachable
4. Check the UDF target URL matches `https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/incidents`
5. Check Activator execution logs in the Fabric portal for error messages

### Incidents not created in Cosmos DB

**Symptoms:** Activator fires but `GET /api/v1/incidents` shows no new `det-` incidents.

**Checks:**
1. Verify API gateway is healthy: `curl https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/health`
2. Check API gateway logs in Container Apps:
   ```bash
   az containerapp logs show \
     --name ca-api-gateway-prod \
     --resource-group rg-aap-prod \
     --follow
   ```
3. Verify the Activator is sending valid JSON matching the `IncidentPayload` schema
4. Check Entra auth — the User Data Function must include a valid Bearer token
5. Verify Cosmos DB connectivity from the gateway

---

## Rollback

To disable the Fabric data-plane and destroy all data-plane resources:

1. In `terraform/envs/prod/main.tf`, set `enable_fabric_data_plane = false`
2. Run:
   ```bash
   terraform -chdir=terraform/envs/prod apply \
     -var-file=credentials.tfvars \
     -target=module.fabric
   ```

> **Note:** The Fabric capacity (`fcaapprod`) is **not** gated by `enable_fabric_data_plane` — it remains provisioned. Only the workspace, Eventhouse, KQL Database, Activator, and Lakehouse are destroyed. This avoids a lengthy capacity re-provisioning cycle if re-activation is needed.

---

## PROD-004 Verification Checklist

- [ ] Fabric workspace `aap-prod` exists and is accessible
- [ ] Eventhouse `eh-aap-prod` has `RawAlerts`, `EnrichedAlerts`, `DetectionResults` tables
- [ ] Eventstream connector is active (Event Hub `eh-alerts-prod` → Eventhouse `kqldb-aap-prod`)
- [ ] Activator trigger fires on `DetectionResults` rows with non-null domain
- [ ] User Data Function posts to `POST /api/v1/incidents` (ca-api-gateway-prod)
- [ ] Test alert flows end-to-end: Azure Monitor → Event Hub → Eventhouse → Activator → API gateway
- [ ] OneLake mirror configured with ≥730 day retention (AUDIT-003)
- [ ] No simulation scripts required — live alerts flow automatically

---

## Related Files

| File | Purpose |
|---|---|
| `scripts/ops/21-2-activate-detection-plane.sh` | Interactive operator runbook (this guide's executable companion) |
| `terraform/modules/fabric/main.tf` | All 5 Fabric data-plane resources + null_resource reminders |
| `terraform/envs/prod/main.tf` | `enable_fabric_data_plane` flag (Plan 21-1) |
| `services/detection-plane/classify_domain.py` | Python mirror of KQL domain classification logic |
| `services/detection-plane/payload_mapper.py` | DetectionResults → IncidentPayload mapping (det- prefix) |
| `services/detection-plane/docs/AUDIT-003-onelake-setup.md` | Full OneLake mirror setup instructions |
| `services/detection-plane/kql/` | KQL function and update policy definitions |

---

## Ongoing Health Monitoring

After the detection plane is activated, use the health check script to verify the pipeline remains operational:

```bash
# Basic health check (no auth required for infrastructure checks)
bash scripts/ops/21-3-detection-health-check.sh

# Full health check including incident verification (requires auth)
export E2E_CLIENT_ID="<client-id>"
export E2E_CLIENT_SECRET="<client-secret>"
bash scripts/ops/21-3-detection-health-check.sh
```

### Health Check Coverage

| Check | What it validates | Requires auth |
|-------|-------------------|---------------|
| Fabric capacity | Capacity is Active | No |
| Fabric workspace | Workspace exists | No |
| Event Hub namespace | Namespace is Active | No |
| Event Hub messages | Hub is configured | No |
| API gateway | Health endpoint returns 200 | No |
| Recent det- incidents | Pipeline is creating incidents | Yes |
| Container App status | Gateway is running | No |

### Recommended Schedule

- **Manual**: After any Terraform apply that touches the fabric module
- **CI**: Add to staging-e2e workflow as a post-deploy check
- **Cron**: Daily at 06:00 UTC for production alerting
