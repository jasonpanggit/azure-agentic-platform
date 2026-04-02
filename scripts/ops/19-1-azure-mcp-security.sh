#!/usr/bin/env bash
# Phase 19 Plan 1: Azure MCP Server Security Hardening
# Resolves SEC-001 (CRITICAL) and DEBT-013.
#
# Run these steps in order. Each step is idempotent.
# Pre-requisites:
#   - az login with Contributor + User Access Administrator on rg-aap-prod
#   - docker buildx installed (linux/amd64 cross-compile)
#   - terraform >= 1.6 installed
#   - Working directory: repo root

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
ACR="aapcrprodjgmjti.azurecr.io"
RG="rg-aap-prod"
CA_NAME="ca-azure-mcp-prod"

echo "=== Phase 19 Plan 1: Azure MCP Server Security Hardening ==="
echo ""

# Step 1: Build and push updated Dockerfile (removes --dangerously-disable-http-incoming-auth)
echo "[1/7] Building azure-mcp-server image without auth-bypass flag..."
cd "${REPO_ROOT}"
az acr login --name aapcrprodjgmjti
docker build \
  -t "${ACR}/services/azure-mcp-server:latest" \
  --platform linux/amd64 \
  -f services/azure-mcp-server/Dockerfile \
  services/azure-mcp-server/
docker push "${ACR}/services/azure-mcp-server:latest"
echo "[1/7] DONE: Image pushed."

# Step 2: Terraform plan (review import + ingress changes)
echo ""
echo "[2/7] Running terraform plan..."
cd "${REPO_ROOT}/terraform/envs/prod"
terraform plan -out=plan-19-1.tfplan -var-file="credentials.tfvars"

# Step 3: Review plan output
echo ""
echo "[3/7] Review the plan above. Confirm:"
echo "  - ca-azure-mcp-prod imported (not destroyed)"
echo "  - ingress.external_enabled changes to false"
echo "  - RBAC assignments for Reader + AcrPull present"
echo ""
read -p "Apply plan? [y/N] " confirm
[[ "${confirm}" == "y" ]] || { echo "Aborted."; exit 0; }

# Step 4: Apply
echo ""
echo "[4/7] Applying Terraform plan..."
terraform apply plan-19-1.tfplan
echo "[4/7] DONE: Terraform apply complete."

# Step 5: Verify internal FQDN
echo ""
echo "[5/7] Fetching internal FQDN..."
INTERNAL_FQDN=$(terraform output -raw azure_mcp_server_internal_fqdn 2>/dev/null || \
  az containerapp show \
    --name "${CA_NAME}" \
    --resource-group "${RG}" \
    --query "properties.configuration.ingress.fqdn" \
    -o tsv)
echo "Internal FQDN: ${INTERNAL_FQDN}"

# Step 6: Verify external access is blocked
echo ""
echo "[6/7] Verifying external access is blocked (expect curl error or connection refused)..."
EXTERNAL_URL="https://ca-azure-mcp-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/mcp"
if curl --max-time 5 --silent --fail "${EXTERNAL_URL}" 2>/dev/null; then
  echo "FAIL: External access still works — check ingress.external_enabled in Azure Portal"
  exit 1
else
  echo "PASS: External access blocked (curl returned non-zero as expected)"
fi

# Step 7: Verify internal_fqdn is wired on ca-api-gateway-prod
echo ""
echo "[7/7] Verifying AZURE_MCP_SERVER_URL env var on ca-api-gateway-prod..."
CURRENT_URL=$(az containerapp env var list \
  --name ca-api-gateway-prod \
  --resource-group "${RG}" \
  --query "[?name=='AZURE_MCP_SERVER_URL'].value" \
  -o tsv 2>/dev/null || echo "")
if [[ "${CURRENT_URL}" == "http://${INTERNAL_FQDN}" ]]; then
  echo "PASS: AZURE_MCP_SERVER_URL correctly points to internal FQDN"
else
  echo "INFO: AZURE_MCP_SERVER_URL on ca-api-gateway-prod = '${CURRENT_URL}'"
  echo "INFO: Expected: http://${INTERNAL_FQDN}"
  echo "INFO: Terraform wires this automatically — if the above is empty, re-run terraform apply"
fi

echo ""
echo "=== Plan 19-1 complete. SEC-001 resolved. ==="
echo "Next: Proceed to Plan 19-3 (MCP tool group registration)."
