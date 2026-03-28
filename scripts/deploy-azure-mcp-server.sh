#!/usr/bin/env bash
# Deploy Azure MCP Server as an internal Container App.
#
# This creates a lightweight Container App running the official Azure MCP Server
# (@azure/mcp) in HTTP transport mode, accessible within the Container Apps
# environment for Foundry agent MCP tool connections.
#
# Usage:
#   ./scripts/deploy-azure-mcp-server.sh
#
# Prerequisites:
#   - az CLI logged in with Contributor on rg-aap-prod
#   - Container Apps environment exists

set -euo pipefail

RESOURCE_GROUP="rg-aap-prod"
ENVIRONMENT="prod"
APP_NAME="ca-azure-mcp-prod"
PORT=8080

# Get Container Apps environment ID
echo "Looking up Container Apps environment..."
CAE_ID=$(az containerapp env list \
  --resource-group "$RESOURCE_GROUP" \
  --query "[0].id" -o tsv)

if [ -z "$CAE_ID" ]; then
  echo "ERROR: No Container Apps environment found in $RESOURCE_GROUP"
  exit 1
fi
echo "  Environment: $CAE_ID"

# Check if the app already exists
EXISTING=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query "name" -o tsv 2>/dev/null || echo "")

if [ -n "$EXISTING" ]; then
  echo "Container App $APP_NAME already exists. Updating..."
  az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "node:20-slim" \
    --set-env-vars "PORT=$PORT" \
    --min-replicas 1 \
    --max-replicas 2 \
    --args "sh","-c","npm install -g @azure/mcp@latest && npx @azure/mcp@latest server start --transport http --port $PORT"
else
  echo "Creating Container App $APP_NAME..."
  az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$CAE_ID" \
    --image "node:20-slim" \
    --target-port "$PORT" \
    --ingress "internal" \
    --transport "http" \
    --cpu 0.5 \
    --memory "1Gi" \
    --min-replicas 1 \
    --max-replicas 2 \
    --env-vars "PORT=$PORT" \
    --command "sh" "-c" "npm install -g @azure/mcp@latest && npx @azure/mcp@latest server start --transport http --port $PORT" \
    --system-assigned
fi

# Get the internal FQDN
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo ""
echo "Azure MCP Server deployed at: https://$FQDN"
echo ""

# Get managed identity principal ID for RBAC
PRINCIPAL_ID=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "identity.principalId" -o tsv)
echo "Managed Identity Principal ID: $PRINCIPAL_ID"

# Grant Reader role on the subscription
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo ""
echo "Granting Reader role on subscription $SUBSCRIPTION_ID..."
az role assignment create \
  --assignee "$PRINCIPAL_ID" \
  --role "Reader" \
  --scope "/subscriptions/$SUBSCRIPTION_ID" \
  --only-show-errors || echo "  (Role may already be assigned)"

echo ""
echo "=== Next Steps ==="
echo "1. Create MCP connection on Foundry account:"
echo ""
echo "   az rest --method PUT \\"
echo "     --url 'https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod/connections/azure-mcp-connection?api-version=2026-01-01-preview' \\"
echo "     --body '{\"properties\":{\"category\":\"MCP\",\"target\":\"https://$FQDN\",\"authType\":\"None\"}}'"
echo ""
echo "2. Update orchestrator assistant with MCP tools:"
echo ""
echo "   AZURE_PROJECT_ENDPOINT='https://aap-foundry-prod.services.ai.azure.com/api/projects/aap-project-prod' \\"
echo "   ORCHESTRATOR_AGENT_ID='asst_NeBVjCA5isNrIERoGYzRpBTu' \\"
echo "   python3 scripts/configure-orchestrator.py --mcp-connection azure-mcp-connection"
