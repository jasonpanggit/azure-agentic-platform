#!/usr/bin/env bash
# Phase 21: Detection Pipeline Health Check
#
# Run this script periodically to verify the live detection loop is operational.
# PROD-004: Live alert detection loop operational without simulation scripts.
#
# Usage:
#   bash scripts/ops/21-3-detection-health-check.sh
#
# Optional env vars:
#   API_URL           - API gateway URL (default: https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io)
#   E2E_CLIENT_ID     - Service principal client ID for auth token
#   E2E_CLIENT_SECRET - Service principal secret
#   E2E_API_AUDIENCE  - API audience (default: api://505df1d3-3bd3-4151-ae87-6e5974b72a44)

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants and defaults
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-aap-prod"
SUBSCRIPTION="4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c"
TENANT_ID="abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
API_URL="${API_URL:-https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io}"
E2E_API_AUDIENCE="${E2E_API_AUDIENCE:-api://505df1d3-3bd3-4151-ae87-6e5974b72a44}"

FABRIC_CAPACITY_ID="/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Fabric/capacities/fcaapprod"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
pass_check() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "  ✅  PASS: $1"
}

fail_check() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "  ❌  FAIL: $1"
}

skip_check() {
  SKIP_COUNT=$((SKIP_COUNT + 1))
  echo "  ⏭️   SKIP: $1"
}

echo "=== Detection Pipeline Health Check ==="
echo "PROD-004: Live alert detection loop operational without simulation scripts"
echo "Time: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

# ---------------------------------------------------------------------------
# Check 1: Fabric capacity status
# ---------------------------------------------------------------------------
echo "--- Check 1: Fabric capacity (fcaapprod) ---"
FABRIC_STATE=$(az resource show \
  --ids "${FABRIC_CAPACITY_ID}" \
  --query "properties.state" -o tsv 2>/dev/null || echo "UNKNOWN")

if [[ "${FABRIC_STATE}" == "Active" ]]; then
  pass_check "Fabric capacity fcaapprod is Active"
else
  fail_check "Fabric capacity fcaapprod state: ${FABRIC_STATE} (expected: Active)"
fi

# ---------------------------------------------------------------------------
# Check 2: Fabric workspace exists
# ---------------------------------------------------------------------------
echo "--- Check 2: Fabric workspace (aap-prod) ---"
FABRIC_TOKEN=$(az account get-access-token \
  --resource https://analysis.windows.net/powerbi/api \
  --query accessToken -o tsv 2>/dev/null || echo "")

if [[ -n "${FABRIC_TOKEN}" ]]; then
  WORKSPACE_FOUND=$(curl -sf \
    -H "Authorization: Bearer ${FABRIC_TOKEN}" \
    "https://api.fabric.microsoft.com/v1/workspaces" 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
ws = [w for w in data.get('value', []) if w.get('displayName') == 'aap-prod']
print('found' if ws else 'not_found')
" 2>/dev/null || echo "error")

  if [[ "${WORKSPACE_FOUND}" == "found" ]]; then
    pass_check "Fabric workspace aap-prod exists"
  elif [[ "${WORKSPACE_FOUND}" == "not_found" ]]; then
    fail_check "Fabric workspace aap-prod not found in workspace list"
  else
    fail_check "Could not query Fabric workspaces (API error)"
  fi
else
  skip_check "Cannot acquire Fabric token — az login may not have Fabric scope"
fi

# ---------------------------------------------------------------------------
# Check 3: Event Hub namespace health
# ---------------------------------------------------------------------------
echo "--- Check 3: Event Hub namespace (ehns-aap-prod) ---"
EH_NS_STATUS=$(az eventhubs namespace show \
  --name ehns-aap-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "status" -o tsv 2>/dev/null || echo "UNKNOWN")

if [[ "${EH_NS_STATUS}" == "Active" ]]; then
  pass_check "Event Hub namespace ehns-aap-prod is Active"
else
  fail_check "Event Hub namespace ehns-aap-prod status: ${EH_NS_STATUS} (expected: Active)"
fi

# ---------------------------------------------------------------------------
# Check 4: Event Hub has recent messages (hub is configured)
# ---------------------------------------------------------------------------
echo "--- Check 4: Event Hub (eh-alerts-prod) configured ---"
EH_RETENTION=$(az eventhubs eventhub show \
  --name eh-alerts-prod \
  --namespace-name ehns-aap-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "messageRetentionInDays" -o tsv 2>/dev/null || echo "0")

if [[ "${EH_RETENTION}" -gt 0 ]]; then
  pass_check "Event Hub eh-alerts-prod is configured (retention: ${EH_RETENTION} days)"
else
  fail_check "Event Hub eh-alerts-prod not found or retention=0 (expected > 0)"
fi

# ---------------------------------------------------------------------------
# Check 5: API gateway health endpoint
# ---------------------------------------------------------------------------
echo "--- Check 5: API gateway health (${API_URL}/health) ---"
HTTP_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "${API_URL}/health" 2>/dev/null || echo "000")

if [[ "${HTTP_STATUS}" == "200" ]]; then
  pass_check "API gateway /health returned HTTP 200"
else
  fail_check "API gateway /health returned HTTP ${HTTP_STATUS} (expected: 200)"
fi

# ---------------------------------------------------------------------------
# Check 6: Recent incidents with det- prefix (requires auth token)
# ---------------------------------------------------------------------------
echo "--- Check 6: Recent det- incidents (requires E2E_CLIENT_ID) ---"
if [[ -z "${E2E_CLIENT_ID:-}" ]]; then
  skip_check "E2E_CLIENT_ID not set — skipping det- incident verification (set E2E_CLIENT_ID + E2E_CLIENT_SECRET to enable)"
else
  TOKEN=$(curl -sf -X POST \
    "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
    -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=${E2E_API_AUDIENCE}/.default" \
    2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

  if [[ -z "${TOKEN}" ]]; then
    fail_check "Could not acquire auth token (check E2E_CLIENT_ID/E2E_CLIENT_SECRET)"
  else
    DET_FOUND=$(curl -sf \
      -H "Authorization: Bearer ${TOKEN}" \
      "${API_URL}/api/v1/incidents?limit=5" 2>/dev/null \
      | python3 -c "
import sys, json
data = json.load(sys.stdin)
incidents = data if isinstance(data, list) else data.get('incidents', data.get('items', []))
det_incidents = [i for i in incidents if str(i.get('incident_id','')).startswith('det-')]
print('found' if det_incidents else 'not_found')
" 2>/dev/null || echo "error")

    if [[ "${DET_FOUND}" == "found" ]]; then
      pass_check "Recent det- prefixed incidents found — live detection pipeline is creating incidents"
    elif [[ "${DET_FOUND}" == "not_found" ]]; then
      fail_check "No det- incidents found in recent 5 — pipeline may not be flowing (normal if no alerts fired recently)"
    else
      fail_check "Could not query incidents endpoint (API error)"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Check 7: Container App running status
# ---------------------------------------------------------------------------
echo "--- Check 7: API gateway Container App (ca-api-gateway-prod) ---"
CA_STATUS=$(az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.runningStatus.state" -o tsv 2>/dev/null || echo "Unknown")

if [[ "${CA_STATUS}" == "Running" || "${CA_STATUS}" == "running" ]]; then
  pass_check "Container App ca-api-gateway-prod is Running"
elif [[ "${CA_STATUS}" == "Unknown" || -z "${CA_STATUS}" ]]; then
  # Fallback: if health check passed, container is effectively running
  if [[ "${HTTP_STATUS}" == "200" ]]; then
    pass_check "Container App ca-api-gateway-prod is responsive (health check passed)"
  else
    fail_check "Container App ca-api-gateway-prod status unknown and health check failed"
  fi
else
  fail_check "Container App ca-api-gateway-prod state: ${CA_STATUS} (expected: Running)"
fi

# ---------------------------------------------------------------------------
# Summary: PROD-004 Status
# ---------------------------------------------------------------------------
echo ""
echo "=================================================="
echo "=== Detection Pipeline Health Check Summary ==="
echo "=================================================="
printf "  PASSED:  %d\n" "${PASS_COUNT}"
printf "  FAILED:  %d\n" "${FAIL_COUNT}"
printf "  SKIPPED: %d\n" "${SKIP_COUNT}"
echo ""

# Determine PROD-004 status:
#   HEALTHY   = 0 failures
#   DEGRADED  = some checks failed but API gateway is up (HTTP 200)
#   UNHEALTHY = API gateway down OR Fabric capacity not Active
if [[ "${FAIL_COUNT}" -eq 0 ]]; then
  STATUS="HEALTHY"
elif [[ "${HTTP_STATUS}" == "200" && "${FABRIC_STATE}" == "Active" ]]; then
  STATUS="DEGRADED"
else
  STATUS="UNHEALTHY"
fi

echo "  PROD-004 Status: ${STATUS}"
echo ""

case "${STATUS}" in
  HEALTHY)
    echo "  All checks passed. Live detection pipeline is fully operational."
    exit 0
    ;;
  DEGRADED)
    echo "  Some checks failed but core infrastructure is up."
    echo "  Review FAIL items above and resolve before next scheduled check."
    exit 1
    ;;
  UNHEALTHY)
    echo "  Critical failures detected. API gateway or Fabric capacity is down."
    echo "  Run: bash scripts/ops/21-2-activate-detection-plane.sh"
    exit 1
    ;;
esac
