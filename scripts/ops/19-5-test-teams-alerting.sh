#!/usr/bin/env bash
# Phase 19 Plan 5: Teams Proactive Alerting E2E Test
#
# Verifies that Teams proactive alerting is operational end-to-end:
#   1. Checks bot proactive notify readiness (ConversationReference captured)
#   2. Posts a synthetic Sev1 incident to the API gateway
#   3. Confirms the bot notify endpoint is ready (not 503)
#   4. Prints verification checklist for operator confirmation
#
# Prerequisites:
#   - Bot installed in a Teams channel (Task 5 complete)
#   - TEAMS_CHANNEL_ID set on ca-teams-bot-prod (Task 6 complete)
#   - E2E_CLIENT_ID and E2E_CLIENT_SECRET env vars (from GitHub Actions secrets)
#
# Usage:
#   export E2E_CLIENT_ID="<client-id from GitHub secrets>"
#   export E2E_CLIENT_SECRET="<client-secret from GitHub secrets>"
#   bash scripts/ops/19-5-test-teams-alerting.sh

set -euo pipefail

RESOURCE_GROUP="rg-aap-prod"
API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
BOT_URL="https://ca-teams-bot-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
TENANT_ID="abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
API_AUDIENCE="api://505df1d3-3bd3-4151-ae87-6e5974b72a44"
INCIDENT_ID="test-teams-alert-$(date +%s)"

echo "=== Phase 19 Plan 5: Teams Proactive Alerting E2E Test ==="
echo ""

# ---------------------------------------------------------------------------
# Pre-flight: Verify TEAMS_CHANNEL_ID is set on the Container App
# ---------------------------------------------------------------------------
echo "--- Pre-flight: Checking TEAMS_CHANNEL_ID on ca-teams-bot-prod ---"
CHANNEL_ID=$(az containerapp show \
  --name ca-teams-bot-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.template.containers[0].env[?name=='TEAMS_CHANNEL_ID'].value | [0]" \
  -o tsv 2>/dev/null || echo "")

if [[ -z "${CHANNEL_ID}" ]]; then
  echo "WARNING: TEAMS_CHANNEL_ID is empty on ca-teams-bot-prod."
  echo ""
  echo "Complete Task 6 first:"
  echo "  1. Install the bot in a Teams channel (Task 5)"
  echo "  2. Capture the channel ID using one of the methods in Task 6"
  echo "  3. Set it: az containerapp update --name ca-teams-bot-prod \\"
  echo "       --resource-group rg-aap-prod \\"
  echo "       --set-env-vars 'TEAMS_CHANNEL_ID=<channel-id>'"
  echo "  4. Update terraform.tfvars: teams_channel_id = \"<channel-id>\""
  echo ""
else
  echo "OK: TEAMS_CHANNEL_ID is set (${CHANNEL_ID:0:20}...)"
fi

echo ""

# ---------------------------------------------------------------------------
# Check Container App env vars
# ---------------------------------------------------------------------------
echo "--- Container App env var summary ---"
az containerapp show \
  --name ca-teams-bot-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.template.containers[0].env[?name=='BOT_ID' || name=='API_GATEWAY_INTERNAL_URL' || name=='WEB_UI_PUBLIC_URL' || name=='TEAMS_CHANNEL_ID'].{name: name, value: value}" \
  -o table 2>/dev/null || echo "ERROR: Could not retrieve Container App env vars (check az login)"

echo ""

# ---------------------------------------------------------------------------
# Verify Bot Service messaging endpoint
# ---------------------------------------------------------------------------
echo "--- Bot Service messaging endpoint ---"
BOT_ENDPOINT=$(az bot show \
  --name aap-teams-bot-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.endpoint" -o tsv 2>/dev/null || echo "NOT_FOUND")

if [[ "${BOT_ENDPOINT}" == "${BOT_URL}/api/messages" ]]; then
  echo "OK: Bot endpoint is correct: ${BOT_ENDPOINT}"
elif [[ "${BOT_ENDPOINT}" == "NOT_FOUND" ]]; then
  echo "WARNING: Could not retrieve bot endpoint (check az login and permissions)"
else
  echo "WARNING: Bot endpoint mismatch."
  echo "  Expected: ${BOT_URL}/api/messages"
  echo "  Actual:   ${BOT_ENDPOINT}"
  echo "  Update via Azure Portal: Bot Services -> aap-teams-bot-prod -> Configuration -> Messaging endpoint"
fi

echo ""

# ---------------------------------------------------------------------------
# Auth token acquisition
# ---------------------------------------------------------------------------
if [[ -z "${E2E_CLIENT_ID:-}" ]]; then
  echo "INFO: E2E_CLIENT_ID not set. Skipping authenticated API tests."
  echo "Set E2E_CLIENT_ID and E2E_CLIENT_SECRET env vars to run the full test."
  echo ""
  echo "=== Manual verification checklist ==="
  echo "  1. [ ] Bot installed in Teams channel (onInstallationUpdate fired)"
  echo "  2. [ ] TEAMS_CHANNEL_ID set on ca-teams-bot-prod"
  echo "  3. [ ] Bot notify endpoint returns 200/202 (not 503)"
  echo "  4. [ ] POST /api/v1/incidents with Sev1 → Adaptive Card in channel within 2 min"
  echo "  5. [ ] Card contains: resource name, severity, subscription, Investigate button"
  echo "  6. [ ] Container App logs show: '[proactive] card sent' or equivalent"
  echo "  7. [ ] terraform plan shows zero diff after teams_channel_id set in tfvars"
  echo ""
  exit 0
fi

TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=${API_AUDIENCE}/.default" \
  | jq -r '.access_token')

if [[ -z "${TOKEN}" || "${TOKEN}" == "null" ]]; then
  echo "ERROR: Failed to obtain auth token. Check E2E_CLIENT_ID / E2E_CLIENT_SECRET."
  exit 1
fi
echo "OK: Auth token acquired."
echo ""

# ---------------------------------------------------------------------------
# Task 7 Test 1: Check bot notify endpoint readiness (503 = not installed)
# ---------------------------------------------------------------------------
echo "--- Test 1: Bot proactive notify readiness ---"
BOT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BOT_URL}/teams/internal/notify" \
  -H "Content-Type: application/json" \
  -d '{"card_type":"alert","payload":{"incident_id":"readiness-check","severity":"Sev1","affected_resource":"/subscriptions/test/resourceGroups/test/providers/Microsoft.Compute/virtualMachines/vm-test","detection_rule":"TEST","timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","kql_evidence":"readiness check"}}' \
  2>/dev/null || echo "000")

if [[ "${BOT_STATUS}" == "503" ]]; then
  echo "WARNING: Bot notify returns 503 — ConversationReference not yet captured."
  echo "The bot must be installed in a Teams channel first."
  echo ""
  echo "After installing the bot, send it a message in Teams to re-capture the reference."
  echo "Then re-run this test."
elif [[ "${BOT_STATUS}" == "200" || "${BOT_STATUS}" == "202" ]]; then
  echo "OK: Bot notify endpoint ready (HTTP ${BOT_STATUS}) — ConversationReference captured."
else
  echo "Bot notify returned HTTP ${BOT_STATUS}"
fi
echo ""

# ---------------------------------------------------------------------------
# Task 7 Test 2: Inject synthetic incident to trigger proactive alert
# ---------------------------------------------------------------------------
echo "--- Test 2: Inject synthetic Sev1 incident ---"
echo "Incident ID: ${INCIDENT_ID}"
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/api/v1/incidents" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"incident_id\": \"${INCIDENT_ID}\",
    \"severity\": \"Sev1\",
    \"domain\": \"compute\",
    \"affected_resources\": [\"/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-prod-01\"],
    \"detection_rule\": \"CPU_CRITICAL_TEAMS_TEST\",
    \"kql_evidence\": \"avg_cpu_percent = 99 for 20 minutes (TEAMS E2E TEST)\"
  }")

HTTP_CODE=$(echo "${RESPONSE}" | tail -1)
BODY=$(echo "${RESPONSE}" | head -n -1)

echo "HTTP status: ${HTTP_CODE}"
echo "Response: ${BODY}"
echo ""

if [[ "${HTTP_CODE}" == "202" || "${HTTP_CODE}" == "200" || "${HTTP_CODE}" == "201" ]]; then
  echo "OK: Incident posted. Check Teams channel within 2 minutes for Adaptive Card."
else
  echo "WARNING: Unexpected HTTP status ${HTTP_CODE}. Check API gateway logs."
fi

echo ""
echo "=== Expected Adaptive Card in Teams ==="
echo "  Resource:      vm-prod-01"
echo "  Severity:      Sev1"
echo "  Domain:        compute"
echo "  Subscription:  4c727b88-..."
echo "  Investigate button -> Web UI"
echo ""

# ---------------------------------------------------------------------------
# Log check reminder
# ---------------------------------------------------------------------------
echo "=== Container App log commands ==="
echo ""
echo "# Bot logs (check for proactive card send confirmation):"
echo "az containerapp logs show \\"
echo "  --name ca-teams-bot-prod \\"
echo "  --resource-group ${RESOURCE_GROUP} \\"
echo "  --tail 30"
echo ""
echo "# API gateway logs (check for incident dispatch to bot):"
echo "az containerapp logs show \\"
echo "  --name ca-api-gateway-prod \\"
echo "  --resource-group ${RESOURCE_GROUP} \\"
echo "  --tail 30"
echo ""
echo "=== App Insights KQL (verify proactive send) ==="
cat <<'KQL'
traces
| where cloud_RoleName == "ca-teams-bot-prod"
| where message contains "proactive" or message contains "card" or message contains "ConversationReference"
| where timestamp > ago(5m)
| project timestamp, message, severityLevel
| order by timestamp desc
| take 20
KQL
echo ""
echo "=== PROD-005 Success Criteria ==="
echo "  1. [ ] Adaptive Card appeared in channel within 120 seconds of incident post"
echo "  2. [ ] Card contains: resource name, severity (Sev1), subscription, timestamp, Investigate button"
echo "  3. [ ] Bot logs show proactive card send confirmation"
echo "  4. [ ] az containerapp show ... TEAMS_CHANNEL_ID returns non-empty value"
echo "  5. [ ] hasConversationReference() = true (bot notify returns 200/202, not 503)"
echo "  6. [ ] terraform plan on terraform/envs/prod/ shows zero diff"
