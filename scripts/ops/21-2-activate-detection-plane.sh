#!/usr/bin/env bash
# Phase 21 Plan 2: Activate Detection Plane — Operator Runbook
#
# This script guides an operator through the post-terraform apply steps required
# to activate the Fabric detection pipeline in production:
#   - Phase 0: Pre-flight terraform plan check (run BEFORE terraform apply)
#   - Step 1: Verify Fabric resources are provisioned
#   - Step 2: Eventstream connector setup (Event Hub -> Eventhouse)
#   - Step 3: KQL table schema setup in Eventhouse
#   - Step 4: Activator trigger configuration
#   - Step 5: OneLake mirror setup (AUDIT-003)
#   - Step 6: Validation KQL queries
#   - Step 7: End-to-end smoke test
#
# Prerequisites:
#   - Phase 19 complete (all 5 plans applied)
#   - az login with active session on correct subscription
#   - terraform apply on terraform/envs/prod/ completed with
#     enable_fabric_data_plane = true (Plan 21-1)
#   - Fabric capacity fcaapprod is active and has CU quota
#
# Usage:
#   bash scripts/ops/21-2-activate-detection-plane.sh
#
# Reference:
#   - docs/ops/detection-plane-activation.md — full operator guide
#   - terraform/modules/fabric/main.tf — resource definitions and reminders
#   - services/detection-plane/docs/AUDIT-003-onelake-setup.md — OneLake setup

set -euo pipefail

RESOURCE_GROUP="rg-aap-prod"
SUBSCRIPTION="4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c"
ENVIRONMENT="prod"
FABRIC_WORKSPACE="aap-${ENVIRONMENT}"
EVENTHOUSE="eh-aap-${ENVIRONMENT}"
KQL_DATABASE="kqldb-aap-${ENVIRONMENT}"
ACTIVATOR="act-aap-${ENVIRONMENT}"
LAKEHOUSE="lh-aap-${ENVIRONMENT}"
EVENT_HUB_NAMESPACE="ehns-aap-${ENVIRONMENT}"
EVENT_HUB="eh-alerts-${ENVIRONMENT}"
API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

echo "=== Phase 21-2: Activate Detection Plane ==="
echo ""
echo "Environment : ${ENVIRONMENT}"
echo "Resource group: ${RESOURCE_GROUP}"
echo "Subscription: ${SUBSCRIPTION}"
echo ""

# ---------------------------------------------------------------------------
# Phase 0: Pre-flight — Terraform plan verification (run BEFORE terraform apply)
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "PHASE 0: Pre-flight Terraform Plan Verification"
echo "======================================================================"
echo ""
echo "Before running terraform apply, verify the plan shows the expected"
echo "Fabric data-plane resources. Run the following command:"
echo ""
echo "  terraform -chdir=terraform/envs/prod plan \\"
echo "    -var-file=credentials.tfvars \\"
echo "    -target=module.fabric \\"
echo "    -no-color 2>&1 | head -80"
echo ""
echo "Expected: Plan should show the following 5 azapi_resource creates:"
echo "  + azapi_resource.fabric_workspace[0]"
echo "  + azapi_resource.fabric_eventhouse[0]"
echo "  + azapi_resource.fabric_kql_database[0]"
echo "  + azapi_resource.fabric_activator[0]"
echo "  + azapi_resource.fabric_lakehouse[0]"
echo ""
echo "Expected: Plan should also show 2 null_resource creates:"
echo "  + null_resource.activator_setup_reminder[0]"
echo "  + null_resource.onelake_mirror_setup_reminder[0]"
echo ""
echo "WARNING: If the plan shows more than 7 resources changing in the"
echo "  fabric module, investigate before applying — only Fabric data-plane"
echo "  resources should change when enable_fabric_data_plane is first set"
echo "  to true."
echo ""
echo "If the plan output matches expectations, run terraform apply:"
echo "  terraform -chdir=terraform/envs/prod apply \\"
echo "    -var-file=credentials.tfvars \\"
echo "    -target=module.fabric"
echo ""
echo "Then re-run this script to proceed with post-apply manual steps."
echo ""
read -r -p "Have you verified the terraform plan and run terraform apply? [y/N] " TF_CONFIRM
if [[ "${TF_CONFIRM,,}" != "y" ]]; then
  echo "Please run terraform plan + apply first, then re-run this script."
  exit 0
fi

echo ""

# ---------------------------------------------------------------------------
# Pre-flight: Verify az CLI and subscription
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "PRE-FLIGHT: Verifying az CLI session and subscription"
echo "======================================================================"
echo ""

echo "--- Checking az login ---"
az account show --output table 2>/dev/null || {
  echo "ERROR: Not logged in to Azure CLI. Run 'az login' first."
  exit 1
}
echo ""

echo "--- Verifying active subscription ---"
ACTIVE_SUB=$(az account show --query id -o tsv 2>/dev/null || echo "")
if [[ "${ACTIVE_SUB}" != "${SUBSCRIPTION}" ]]; then
  echo "WARNING: Active subscription (${ACTIVE_SUB}) does not match expected (${SUBSCRIPTION})."
  echo "Setting subscription to ${SUBSCRIPTION}..."
  az account set --subscription "${SUBSCRIPTION}"
  echo "OK: Subscription set."
fi
echo "Active subscription: ${SUBSCRIPTION}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Verify Fabric resources provisioned
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 1: Verify Fabric resources provisioned"
echo "======================================================================"
echo ""
echo "Checking Fabric resources in resource group ${RESOURCE_GROUP}..."
echo ""

FABRIC_RESOURCES=$(az resource list \
  --resource-group "${RESOURCE_GROUP}" \
  --query "[?type != null && starts_with(type, 'Microsoft.Fabric')]" \
  -o table 2>/dev/null || echo "QUERY_FAILED")

if [[ "${FABRIC_RESOURCES}" == "QUERY_FAILED" ]]; then
  echo "WARNING: Could not list Fabric resources (check az permissions)."
else
  echo "${FABRIC_RESOURCES}"
fi

echo ""
echo "Checking Fabric workspace via REST API..."
WORKSPACE_STATUS=$(az rest \
  --method GET \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION}/providers/Microsoft.Fabric/workspaces?api-version=2023-11-01" \
  --query "value[?name=='${FABRIC_WORKSPACE}'].{name: name, state: properties.provisioningState}" \
  -o table 2>/dev/null || echo "WORKSPACE_NOT_FOUND")

if [[ "${WORKSPACE_STATUS}" == "WORKSPACE_NOT_FOUND" || -z "${WORKSPACE_STATUS}" ]]; then
  echo "WARNING: Fabric workspace '${FABRIC_WORKSPACE}' not found via REST."
  echo "  This is expected if terraform apply has not completed yet."
  echo "  Verify: terraform output -chdir=terraform/envs/prod | grep fabric"
else
  echo "${WORKSPACE_STATUS}"
  echo "OK: Fabric workspace found."
fi

echo ""
echo "Resources expected after terraform apply:"
echo "  - Workspace: ${FABRIC_WORKSPACE}"
echo "  - Eventhouse: ${EVENTHOUSE}"
echo "  - KQL Database: ${KQL_DATABASE}"
echo "  - Activator: ${ACTIVATOR}"
echo "  - Lakehouse: ${LAKEHOUSE}"
echo ""
read -r -p "Are all 5 Fabric resources provisioned and active? [y/N] " FABRIC_CONFIRM
if [[ "${FABRIC_CONFIRM,,}" != "y" ]]; then
  echo "Please ensure all 5 Fabric resources are provisioned before continuing."
  exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# Step 2: Eventstream connector setup instructions
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 2: Eventstream Connector Setup (Manual — Fabric Portal)"
echo "======================================================================"
echo ""
echo "The Eventstream connector cannot be automated via Terraform or the Fabric REST API."
echo "Follow these steps in the Fabric portal:"
echo ""
echo "  1. Open Fabric portal: https://app.fabric.microsoft.com"
echo "  2. Navigate to workspace: ${FABRIC_WORKSPACE}"
echo "  3. Click New -> Eventstream"
echo "  4. Name the Eventstream: eventstream-alerts-${ENVIRONMENT}"
echo ""
echo "  SOURCE configuration:"
echo "    - Source type: Azure Event Hub"
echo "    - Event Hub namespace: ${EVENT_HUB_NAMESPACE}"
echo "    - Event Hub: ${EVENT_HUB}"
echo "    - Consumer group: \$Default (or create a dedicated one)"
echo "    - Authentication: Connection string (see below)"
echo ""
echo "  Retrieve the Event Hub connection string:"
echo "    az eventhubs namespace authorization-rule keys list \\"
echo "      --resource-group ${RESOURCE_GROUP} \\"
echo "      --namespace-name ${EVENT_HUB_NAMESPACE} \\"
echo "      --name RootManageSharedAccessKey \\"
echo "      --query primaryConnectionString -o tsv"
echo ""
echo "  DESTINATION configuration:"
echo "    - Destination type: Eventhouse"
echo "    - Workspace: ${FABRIC_WORKSPACE}"
echo "    - Eventhouse: ${EVENTHOUSE}"
echo "    - KQL Database: ${KQL_DATABASE}"
echo "    - Table: RawAlerts (create if not exists — see Step 3)"
echo "    - Data format: JSON"
echo ""
echo "  5. Click Publish to activate the Eventstream connector"
echo ""
read -r -p "Have you configured the Eventstream connector? [y/N] " EVENTSTREAM_CONFIRM
if [[ "${EVENTSTREAM_CONFIRM,,}" != "y" ]]; then
  echo "Please configure the Eventstream connector, then re-run or continue manually."
  echo "This step is required before data can flow from Event Hub to Eventhouse."
fi

echo ""

# ---------------------------------------------------------------------------
# Step 3: KQL table schema setup instructions
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 3: KQL Table Schema Setup (Eventhouse — Fabric Portal)"
echo "======================================================================"
echo ""
echo "Run the following KQL commands in the Eventhouse KQL database (${KQL_DATABASE})."
echo "Open the KQL database in the Fabric portal query editor and paste each block:"
echo ""
echo "--- RawAlerts table ---"
cat <<'KQL_SCHEMA'
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
KQL_SCHEMA

echo ""
echo "--- EnrichedAlerts table ---"
cat <<'KQL_SCHEMA'
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
KQL_SCHEMA

echo ""
echo "--- DetectionResults table ---"
cat <<'KQL_SCHEMA'
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
KQL_SCHEMA

echo ""
echo "After creating tables, apply the KQL update policies from:"
echo "  services/detection-plane/kql/ (classify_domain function + update policies)"
echo ""
read -r -p "Have you created all 3 KQL tables (RawAlerts, EnrichedAlerts, DetectionResults)? [y/N] " KQL_CONFIRM
if [[ "${KQL_CONFIRM,,}" != "y" ]]; then
  echo "Please create the KQL tables, then re-run or continue manually."
fi

echo ""

# ---------------------------------------------------------------------------
# Step 4: Activator trigger configuration
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 4: Activator Trigger Configuration (Manual — Fabric Portal)"
echo "======================================================================"
echo ""
echo "The Activator trigger must be configured manually via the Fabric portal."
echo "This is documented in terraform/modules/fabric/main.tf (null_resource.activator_setup_reminder)."
echo ""
echo "Steps:"
echo "  1. Open Fabric portal: https://app.fabric.microsoft.com"
echo "  2. Navigate to workspace: ${FABRIC_WORKSPACE}"
echo "  3. Open Activator: ${ACTIVATOR}"
echo "  4. Click 'Set data source'"
echo "     - Source: Eventhouse"
echo "     - Eventhouse: ${EVENTHOUSE}"
echo "     - KQL Database: ${KQL_DATABASE}"
echo "     - Table: DetectionResults"
echo "  5. Set trigger condition:"
echo "     - Condition: New row where domain IS NOT NULL"
echo "     - This ensures only classified alerts (with a valid domain) trigger the agent"
echo "  6. Set trigger action:"
echo "     - Action type: User Data Function"
echo "     - Function: handle_activator_trigger"
echo "     - The UDF posts to POST /api/v1/incidents on ${API_URL}"
echo "  7. Click Save and activate the trigger"
echo ""
echo "  Reference: terraform/modules/fabric/main.tf null_resource.activator_setup_reminder"
echo ""
read -r -p "Have you configured the Activator trigger (domain IS NOT NULL -> handle_activator_trigger)? [y/N] " ACTIVATOR_CONFIRM
if [[ "${ACTIVATOR_CONFIRM,,}" != "y" ]]; then
  echo "Please configure the Activator trigger, then re-run or continue manually."
fi

echo ""

# ---------------------------------------------------------------------------
# Step 5: OneLake mirror setup (AUDIT-003)
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 5: OneLake Mirror Setup (AUDIT-003 Compliance)"
echo "======================================================================"
echo ""
echo "Configure the Activity Log OneLake mirror for 2-year retention (AUDIT-003)."
echo "Full instructions: services/detection-plane/docs/AUDIT-003-onelake-setup.md"
echo ""
echo "Summary steps:"
echo "  1. Open Fabric portal: https://app.fabric.microsoft.com"
echo "  2. Navigate to workspace: ${FABRIC_WORKSPACE}"
echo "  3. Open Lakehouse: ${LAKEHOUSE}"
echo ""
echo "  Option A: OneLake Shortcut (preferred)"
echo "    - Click 'Get data' -> 'New shortcut'"
echo "    - Source: Azure Data Lake Storage Gen2"
echo "    - URL: Log Analytics workspace export storage account URL"
echo "    - Path: /AzureActivityLog/"
echo "    - Shortcut name: ActivityLog"
echo ""
echo "  Option B: Fabric Data Pipeline (if shortcut unavailable)"
echo "    - New -> Data Pipeline -> pipeline-activity-log-mirror"
echo "    - Copy Data: Source = Log Analytics, Destination = Lakehouse (Delta format)"
echo "    - Schedule: every 1 hour"
echo ""
echo "  Configure retention (>= 730 days / 2 years per AUDIT-003):"
echo "    - Open ActivityLog table -> Table properties -> Retention policy"
echo "    - Set to 730 days"
echo "    OR run in a Fabric Spark notebook:"
echo ""
cat <<'SPARK_SQL'
    spark.sql("""
    ALTER TABLE ActivityLog
    SET TBLPROPERTIES (
      'delta.deletedFileRetentionDuration' = 'interval 730 days',
      'delta.logRetentionDuration' = 'interval 730 days'
    )
    """)
SPARK_SQL

echo ""
read -r -p "Have you configured the OneLake mirror with >= 730 day retention? [y/N] " ONELAKE_CONFIRM
if [[ "${ONELAKE_CONFIRM,,}" != "y" ]]; then
  echo "Please configure the OneLake mirror. AUDIT-003 compliance requires this step."
fi

echo ""

# ---------------------------------------------------------------------------
# Step 6: Validation KQL queries
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 6: Validation KQL Queries"
echo "======================================================================"
echo ""
echo "Run these KQL queries in the Eventhouse (${KQL_DATABASE}) to validate the pipeline."
echo "Open the KQL database query editor in the Fabric portal and run each query:"
echo ""
echo "--- Check RawAlerts table exists and has data ---"
cat <<'KQL_VALIDATE'
RawAlerts | count
KQL_VALIDATE

echo ""
echo "--- Check enrichment pipeline ---"
cat <<'KQL_VALIDATE'
EnrichedAlerts
| where classified_at > ago(1h)
| count
KQL_VALIDATE

echo ""
echo "--- Check classification pipeline: sample DetectionResults with domain ---"
cat <<'KQL_VALIDATE'
DetectionResults
| where domain != ""
| take 5
KQL_VALIDATE

echo ""
echo "--- Pipeline health: alerts processed in last hour by domain ---"
cat <<'KQL_VALIDATE'
DetectionResults
| where classified_at > ago(1h)
| summarize Count=count() by domain
| order by Count desc
KQL_VALIDATE

echo ""
echo "Expected: After the Eventstream connector is active and Azure Monitor alerts"
echo "are flowing, RawAlerts.count should be > 0 and DetectionResults should show"
echo "rows with non-empty domain values (compute, network, storage, security, arc, sre)."
echo ""

# ---------------------------------------------------------------------------
# Step 7: End-to-end smoke test
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "STEP 7: End-to-End Smoke Test"
echo "======================================================================"
echo ""
echo "To verify the complete pipeline from Azure Monitor -> Eventhouse -> Activator -> API:"
echo ""
echo "  1. Fire a test Azure Monitor metric alert:"
echo "     az monitor metrics alert create \\"
echo "       --name test-detection-plane-alert \\"
echo "       --resource-group ${RESOURCE_GROUP} \\"
echo "       --scopes /subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP} \\"
echo "       --condition 'avg Percentage CPU > 0' \\"
echo "       --description 'Test alert for detection plane validation'"
echo ""
echo "     Or trigger an existing alert rule by updating a threshold temporarily."
echo ""
echo "  2. Wait 60 seconds for the alert to flow through the pipeline"
echo ""
echo "  3. Check DetectionResults in Eventhouse KQL editor:"
cat <<'KQL_SMOKE'
DetectionResults
| where fired_at > ago(5m)
| take 1
KQL_SMOKE

echo ""
echo "  4. Verify incident was created in Cosmos DB via the API gateway:"
echo "     curl -s \\"
echo "       -H 'Authorization: Bearer <token>' \\"
echo "       '${API_URL}/api/v1/incidents?limit=1'"
echo ""
echo "     Expected: Response contains incident with incident_id starting with 'det-'"
echo "     (e.g., det-<alert_id>) — the 'det-' prefix confirms the incident was"
echo "     created by the detection plane payload_mapper.py"
echo ""
echo "  5. Check Application Insights for the agent trace:"
echo "     - App Insights KQL to verify end-to-end:"
cat <<'KQL_APPINSIGHTS'
requests
| where cloud_RoleName == "ca-api-gateway-prod"
| where url contains "/api/v1/incidents"
| where timestamp > ago(10m)
| project timestamp, resultCode, url, duration
| order by timestamp desc
| take 10
KQL_APPINSIGHTS

echo ""

# ---------------------------------------------------------------------------
# PROD-004 Verification Checklist
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "=== PROD-004 Verification Checklist ==="
echo "======================================================================"
echo ""
echo "Mark each item complete before closing Phase 21:"
echo ""
echo "  [ ] Fabric workspace ${FABRIC_WORKSPACE} exists and is accessible"
echo "  [ ] Eventhouse ${EVENTHOUSE} has RawAlerts, EnrichedAlerts, DetectionResults tables"
echo "  [ ] Eventstream connector is active (Event Hub ${EVENT_HUB} -> Eventhouse ${KQL_DATABASE})"
echo "  [ ] Activator trigger fires on DetectionResults rows with non-null domain"
echo "  [ ] User Data Function (handle_activator_trigger) posts to POST /api/v1/incidents"
echo "  [ ] Test alert flows end-to-end: Azure Monitor -> Event Hub -> Eventhouse -> Activator -> API gateway"
echo "  [ ] OneLake mirror configured with >= 730 day retention (AUDIT-003)"
echo "  [ ] No simulation scripts required — live alerts flow automatically"
echo ""
echo "=== Detection plane activation complete ==="
echo ""
echo "Reference: docs/ops/detection-plane-activation.md — full operator guide with"
echo "architecture diagram, troubleshooting, and rollback procedure."
