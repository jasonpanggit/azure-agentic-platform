#!/usr/bin/env bash
# Phase 19 Plan 3: MCP Tool Group Registration Verification
#
# Prerequisites:
#   - Plan 19-1 (Azure MCP Server internal ingress) must be applied first
#   - Plan 19-2 (Auth enablement) must be applied first (for Bearer token)
#   - terraform apply on terraform/envs/prod/ must be complete
#
# Usage:
#   bash scripts/ops/19-3-register-mcp-connections.sh
#
# Authenticated tool tests (optional):
#   export E2E_CLIENT_ID="<client-id from GitHub Actions secrets>"
#   export E2E_CLIENT_SECRET="<client-secret from GitHub Actions secrets>"
#   export E2E_API_AUDIENCE="api://505df1d3-3bd3-4151-ae87-6e5974b72a44"
#   bash scripts/ops/19-3-register-mcp-connections.sh

set -euo pipefail

RESOURCE_GROUP="rg-aap-prod"
FOUNDRY_ACCOUNT="aap-foundry-prod"
FOUNDRY_PROJECT="aap-project-prod"
SUBSCRIPTION="4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c"

echo "=== Phase 19-3: MCP Tool Group Registration ==="
echo ""

# ---------------------------------------------------------------------------
# Task 1: Verify Arc MCP Server real image is running
# ---------------------------------------------------------------------------
echo "--- Task 1: Verify Arc MCP Server image ---"
ARC_MCP_IMAGE=$(az containerapp show \
  --name ca-arc-mcp-server-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.template.containers[0].image" -o tsv 2>/dev/null || echo "NOT_FOUND")

echo "Arc MCP Server image: ${ARC_MCP_IMAGE}"
if [[ "${ARC_MCP_IMAGE}" == *"containerapps-helloworld"* ]]; then
  echo "WARNING: Placeholder image still running. Build and push the real image:"
  echo ""
  echo "  az acr login --name aapcrprodjgmjti"
  echo "  docker build -t aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest \\"
  echo "    --platform linux/amd64 \\"
  echo "    -f services/arc-mcp-server/Dockerfile \\"
  echo "    services/arc-mcp-server/"
  echo "  docker push aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest"
  echo "  az containerapp update \\"
  echo "    --name ca-arc-mcp-server-prod \\"
  echo "    --resource-group ${RESOURCE_GROUP} \\"
  echo "    --image aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest"
  echo ""
  echo "Then re-run this script."
  exit 1
elif [[ "${ARC_MCP_IMAGE}" == "NOT_FOUND" ]]; then
  echo "ERROR: ca-arc-mcp-server-prod not found. Run terraform apply first."
  exit 1
else
  echo "OK: Real image deployed."
fi

echo ""

# ---------------------------------------------------------------------------
# Task 2: Get internal FQDNs (after Plan 19-1 internal ingress is applied)
# ---------------------------------------------------------------------------
echo "--- Task 2: Retrieve internal FQDNs ---"
AZURE_MCP_FQDN=$(az containerapp show \
  --name ca-azure-mcp-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")

ARC_MCP_FQDN=$(az containerapp show \
  --name ca-arc-mcp-server-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")

echo "Azure MCP Server internal FQDN: ${AZURE_MCP_FQDN:-NOT_FOUND}"
echo "Arc MCP Server internal FQDN:   ${ARC_MCP_FQDN:-NOT_FOUND}"

if [[ -z "${AZURE_MCP_FQDN}" ]]; then
  echo "ERROR: ca-azure-mcp-prod not found or no ingress FQDN. Run terraform apply first."
  exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# MCP Connection Verification (list registered connections on Foundry project)
# ---------------------------------------------------------------------------
echo "=== MCP Connection Verification ==="
echo "Foundry project MCP connections:"
az rest \
  --method GET \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT}/projects/${FOUNDRY_PROJECT}/connections?api-version=2026-01-01-preview" \
  --query "value[?properties.category=='MCP'].{name: name, target: properties.target, auth: properties.authType}" \
  -o table 2>/dev/null || {
    echo "WARNING: Could not query Foundry connections (check az login and RBAC)."
  }

echo ""
echo "=== Domain Agent Tool Group Verification ==="
echo "Testing via API gateway chat endpoint (requires auth token)..."

# Get auth token (requires E2E_CLIENT_ID/SECRET to be set)
if [[ -z "${E2E_CLIENT_ID:-}" ]]; then
  echo "INFO: E2E_CLIENT_ID not set. Skipping authenticated tool tests."
  echo "Set E2E_CLIENT_ID, E2E_CLIENT_SECRET, E2E_API_AUDIENCE env vars to run authenticated tests."
  echo ""
  echo "=== Operator Checklist ==="
  echo "Before marking PROD-003 resolved, verify:"
  echo "  1. [ ] terraform apply completed with 2 azapi_resource creates"
  echo "  2. [ ] Foundry connections list shows azure-mcp-connection + arc-mcp-connection"
  echo "  3. [ ] Network agent NSG query: no 'tool group was not found' in response"
  echo "  4. [ ] Security agent Defender query: no 'tool group was not found' in response"
  echo "  5. [ ] Arc agent list Arc servers: no 'tool group was not found' in response"
  echo "  6. [ ] SRE agent Service Health query: no 'tool group was not found' in response"
  echo "  7. [ ] App Insights mcp.outcome: success spans visible from all 4 agents"
  echo ""
  echo "App Insights KQL to verify:"
  cat <<'KQL'
  dependencies
  | where cloud_RoleName in ("ca-network-prod", "ca-security-prod", "ca-arc-prod", "ca-sre-prod")
  | where name startswith "mcp."
  | where timestamp > ago(1h)
  | summarize count() by cloud_RoleName, name, success
  | order by cloud_RoleName, name
KQL
  exit 0
fi

TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/abbdca26-d233-4a1e-9d8c-c4eebbc16e50/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=${E2E_API_AUDIENCE}/.default" \
  | jq -r '.access_token')

API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

echo ""
echo "--- Test 1: Network Agent (Microsoft.Network tool group) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "List NSG rules in the prod subscription", "domain": "network"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "--- Test 2: Security Agent (Microsoft.Security tool group) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the Defender for Cloud secure score?", "domain": "security"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "--- Test 3: Arc Agent (Arc MCP Server tool group) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "List all Arc-enabled servers", "domain": "arc"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "--- Test 4: SRE Agent (Monitor + Log Analytics tool groups) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "Show Azure Service Health events in the last 24 hours", "domain": "sre"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "=== Verification complete ==="
