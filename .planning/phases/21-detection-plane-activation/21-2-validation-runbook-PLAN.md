# Plan 21-2: Validation & Operator Runbook

---
wave: 2
depends_on:
  - 21-1-terraform-activation-PLAN.md
files_modified:
  - scripts/ops/21-2-activate-detection-plane.sh
  - docs/ops/detection-plane-activation.md
requirements:
  - PROD-004
autonomous: true
---

## Objective

Create the operator runbook that guides a human through the post-`terraform apply` manual steps (Activator trigger wiring, Eventstream connector, OneLake mirror) and includes validation KQL queries to prove the pipeline is live. Also create the validation script that verifies the Fabric resources are provisioned and the detection pipeline is flowing data.

## Tasks

<task id="21-2-01">
<title>Create operator runbook script: scripts/ops/21-2-activate-detection-plane.sh</title>
<read_first>
- scripts/ops/19-3-register-mcp-connections.sh (style reference for operator runbooks: pre-flight checks, step-by-step, validation)
- scripts/ops/19-4-seed-runbooks.sh (another style reference)
- terraform/modules/fabric/main.tf (null_resource reminders for manual steps)
- services/detection-plane/docs/AUDIT-003-onelake-setup.md (OneLake mirror steps)
- services/detection-plane/payload_mapper.py (incident_id uses "det-" prefix)
</read_first>
<action>
Create `scripts/ops/21-2-activate-detection-plane.sh` with the following structure:

1. **Shebang and header**: `#!/usr/bin/env bash` with `set -euo pipefail`
2. **Constants**: `RESOURCE_GROUP="rg-aap-prod"`, `SUBSCRIPTION="4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c"`, `ENVIRONMENT="prod"`
3. **Pre-flight checks section**:
   - Verify `az` CLI is logged in (`az account show`)
   - Verify correct subscription is active
   - Verify terraform apply has been run (check Fabric resources exist via `az resource list --resource-group $RESOURCE_GROUP --resource-type Microsoft.Fabric/capacities`)
4. **Step 1: Verify Fabric resources provisioned** — use `az rest` to query Fabric workspace, Eventhouse, KQL Database, Activator, and Lakehouse. Print resource IDs and status. Fail if any are missing.
5. **Step 2: Eventstream connector setup instructions** — echo clear instructions for:
   - Open Fabric portal at `https://app.fabric.microsoft.com`
   - Navigate to workspace `aap-prod`
   - Create Eventstream: source = Azure Event Hub (`eh-alerts-prod` on namespace `ehns-aap-prod`), destination = Eventhouse KQL DB `kqldb-aap-prod`, table = `RawAlerts`
   - Provide the Event Hub connection string retrieval command: `az eventhubs namespace authorization-rule keys list --resource-group $RESOURCE_GROUP --namespace-name ehns-aap-prod --name RootManageSharedAccessKey --query primaryConnectionString -o tsv`
6. **Step 3: KQL table schema setup instructions** — echo the KQL commands to create tables in the Eventhouse:
   ```
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
7. **Step 4: Activator trigger configuration** — echo step-by-step instructions:
   - Open Activator `act-aap-prod` in Fabric workspace
   - Set data source: Eventhouse `DetectionResults` table in `kqldb-aap-prod`
   - Set trigger condition: `new row where domain IS NOT NULL`
   - Set action: invoke User Data Function `handle_activator_trigger`
   - Reference: `terraform/modules/fabric/main.tf` null_resource.activator_setup_reminder
8. **Step 5: OneLake mirror setup** — reference `services/detection-plane/docs/AUDIT-003-onelake-setup.md` and echo summary steps
9. **Step 6: Validation KQL queries** — echo the following queries for operator to run in Eventhouse:
   ```kql
   // Check RawAlerts table exists and has data
   RawAlerts | count

   // Check enrichment pipeline
   EnrichedAlerts | where classified_at > ago(1h) | count

   // Check classification pipeline
   DetectionResults | where domain != "" | take 5

   // Pipeline health: alerts processed in last hour
   DetectionResults
   | where classified_at > ago(1h)
   | summarize Count=count() by domain
   | order by Count desc
   ```
10. **Step 7: End-to-end smoke test** — echo instructions to:
    - Fire a test Azure Monitor alert via `az monitor metrics alert create` (or use an existing alert rule)
    - Wait 60 seconds
    - Query `DetectionResults | where fired_at > ago(5m) | take 1` to confirm it arrived
    - Query Cosmos DB via API: `curl -s https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/incidents?limit=1` with auth header to confirm incident was created with `det-` prefix
11. **PROD-004 checklist** at the end:
    ```
    === PROD-004 Verification Checklist ===
    [ ] Fabric workspace aap-prod exists and is accessible
    [ ] Eventhouse eh-aap-prod has RawAlerts, EnrichedAlerts, DetectionResults tables
    [ ] Eventstream connector is active (Event Hub -> Eventhouse)
    [ ] Activator trigger fires on DetectionResults rows with non-null domain
    [ ] User Data Function posts to POST /api/v1/incidents
    [ ] Test alert flows end-to-end: Azure Monitor -> Event Hub -> Eventhouse -> Activator -> API gateway
    [ ] OneLake mirror configured with >= 730 day retention (AUDIT-003)
    [ ] No simulation scripts required — live alerts flow automatically
    ```

Make the file executable: `chmod +x scripts/ops/21-2-activate-detection-plane.sh`
</action>
<acceptance_criteria>
- File exists at `scripts/ops/21-2-activate-detection-plane.sh`
- `head -1 scripts/ops/21-2-activate-detection-plane.sh` outputs `#!/usr/bin/env bash`
- `grep "set -euo pipefail" scripts/ops/21-2-activate-detection-plane.sh` returns a match
- `grep "RESOURCE_GROUP=" scripts/ops/21-2-activate-detection-plane.sh` returns `rg-aap-prod`
- `grep "PROD-004" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match (the checklist)
- `grep "RawAlerts" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "EnrichedAlerts" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "DetectionResults" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "Activator" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "OneLake" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "domain IS NOT NULL" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "det-" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "az account show" scripts/ops/21-2-activate-detection-plane.sh` returns a match (pre-flight)
- `test -x scripts/ops/21-2-activate-detection-plane.sh` exits 0 (executable)
- `bash -n scripts/ops/21-2-activate-detection-plane.sh` exits 0 (valid bash syntax)
</acceptance_criteria>
</task>

<task id="21-2-02">
<title>Create operator documentation: docs/ops/detection-plane-activation.md</title>
<read_first>
- docs/ops/runbook-seeding.md (style reference for operator guides)
- services/detection-plane/docs/AUDIT-003-onelake-setup.md (OneLake setup details to reference)
- terraform/modules/fabric/main.tf (null_resource reminder text)
- services/detection-plane/classify_domain.py (DOMAIN_MAPPINGS for reference)
- services/detection-plane/payload_mapper.py (payload mapping logic)
</read_first>
<action>
Create `docs/ops/detection-plane-activation.md` with the following sections:

1. **Title**: `# Detection Plane Activation Guide`
2. **Overview**: Explain that Phase 21 activates the Fabric detection pipeline in production. The pipeline was designed in Phase 4 and the infrastructure is managed by Terraform. After `terraform apply`, manual steps are required to wire the Eventstream, Activator trigger, and OneLake mirror.
3. **Prerequisites**:
   - Phase 19 complete (all plans applied — MCP security, auth, tool groups, runbook RAG, Teams alerting)
   - `terraform apply` on `terraform/envs/prod/` completed with `enable_fabric_data_plane = true`
   - Fabric capacity `fcaapprod` is active and has CU quota
   - Event Hub namespace `ehns-aap-prod` is provisioned and receiving Azure Monitor alerts
   - API gateway `ca-api-gateway-prod` is healthy and accepting `POST /api/v1/incidents`
4. **Architecture diagram** (ASCII):
   ```
   Azure Monitor Alerts
          |
          v
   Event Hub (ehns-aap-prod / eh-alerts-prod)
          |
          v (Eventstream connector)
   Eventhouse (eh-aap-prod)
     RawAlerts table
          |
          v (KQL update policy)
     EnrichedAlerts table
          |
          v (KQL classify_domain)
     DetectionResults table
          |
          v (Activator trigger: domain IS NOT NULL)
   Fabric Activator (act-aap-prod)
          |
          v (User Data Function)
   POST /api/v1/incidents (ca-api-gateway-prod)
          |
          v
   Orchestrator -> Domain Agent -> Triage
   ```
5. **Step-by-step procedure**: Reference `scripts/ops/21-2-activate-detection-plane.sh` for the automated pre-flight checks and manual instructions
6. **Domain classification reference**: List all domain mappings from `classify_domain.py` for operator reference
7. **Troubleshooting**:
   - Alerts not appearing in RawAlerts: Check Eventstream connector status, Event Hub connection string, data format
   - Alerts not enriched: Check KQL update policy is attached to RawAlerts
   - DetectionResults has empty domain: Check classify_domain function and resource_type values
   - Activator not triggering: Verify trigger condition, check Activator status in Fabric portal
   - Incidents not created: Check API gateway health, auth configuration, Activator webhook URL
8. **Rollback**: Set `enable_fabric_data_plane = false` in terraform.tfvars and run `terraform apply` to destroy Fabric data-plane resources (capacity stays)
</action>
<acceptance_criteria>
- File exists at `docs/ops/detection-plane-activation.md`
- `grep "Detection Plane Activation" docs/ops/detection-plane-activation.md` returns a match
- `grep "Prerequisites" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "enable_fabric_data_plane" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "ehns-aap-prod" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "classify_domain" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "Troubleshooting" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "Rollback" docs/ops/detection-plane-activation.md` returns at least 1 match
- `grep "21-2-activate-detection-plane" docs/ops/detection-plane-activation.md` returns at least 1 match (cross-reference to script)
</acceptance_criteria>
</task>

<task id="21-2-03">
<title>Create pre-flight validation script for terraform plan verification</title>
<read_first>
- terraform/modules/fabric/main.tf (all 5 counted resources)
- terraform/modules/fabric/outputs.tf (output names)
- terraform/envs/prod/main.tf (the fabric module block)
</read_first>
<action>
Create a lightweight validation section at the TOP of `scripts/ops/21-2-activate-detection-plane.sh` (in task 21-2-01) that:

1. Runs `terraform -chdir=terraform/envs/prod plan -var-file=credentials.tfvars -target=module.fabric -no-color 2>&1 | head -50` (or guides the operator to do so)
2. Asserts the plan shows 5 resources to add:
   - `azapi_resource.fabric_workspace[0]`
   - `azapi_resource.fabric_eventhouse[0]`
   - `azapi_resource.fabric_kql_database[0]`
   - `azapi_resource.fabric_activator[0]`
   - `azapi_resource.fabric_lakehouse[0]`
3. Asserts the plan shows 2 null_resource creates:
   - `null_resource.activator_setup_reminder[0]`
   - `null_resource.onelake_mirror_setup_reminder[0]`
4. Warns if more than 7 resources are being changed (safety guard — only fabric resources should change)

This is a PRE-APPLY check. The script should echo the expected terraform plan output and ask the operator to verify before proceeding.

NOTE: This task modifies the same file as 21-2-01. The executor should integrate this into the script created in 21-2-01 as a "Phase 0: Pre-flight" section before Step 1.
</action>
<acceptance_criteria>
- `grep "terraform.*plan" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "fabric_workspace" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "fabric_eventhouse" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "fabric_kql_database" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "fabric_activator" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "fabric_lakehouse" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
- `grep "null_resource" scripts/ops/21-2-activate-detection-plane.sh` returns at least 1 match
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
1. `scripts/ops/21-2-activate-detection-plane.sh` exists, is executable, and passes `bash -n` syntax check
2. `docs/ops/detection-plane-activation.md` exists with all required sections
3. Script contains pre-flight checks, 7 numbered steps, and PROD-004 checklist
4. Documentation cross-references the script and covers troubleshooting + rollback

## must_haves

- [ ] Operator runbook script at `scripts/ops/21-2-activate-detection-plane.sh` with pre-flight checks
- [ ] Script includes Eventstream connector setup instructions
- [ ] Script includes Activator trigger wiring instructions (domain IS NOT NULL condition)
- [ ] Script includes OneLake mirror reference
- [ ] Script includes KQL validation queries for RawAlerts, EnrichedAlerts, DetectionResults
- [ ] Script includes end-to-end smoke test instructions (fire alert -> verify in DetectionResults -> verify in Cosmos)
- [ ] Script includes PROD-004 verification checklist
- [ ] Operator documentation at `docs/ops/detection-plane-activation.md`
- [ ] Documentation includes architecture diagram, troubleshooting, and rollback procedure
