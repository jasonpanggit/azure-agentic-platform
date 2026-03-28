#!/usr/bin/env bash
# Grant Cosmos DB Built-in Data Contributor to all agent managed identities.
#
# This role is a Cosmos data-plane role assigned via the Cosmos API (not ARM RBAC),
# so it cannot be managed by Terraform's azurerm_role_assignment.
#
# Usage: ./scripts/grant-cosmos-rbac.sh
# Requires: az CLI, Contributor or Owner on the Cosmos account
#
# Role: 00000000-0000-0000-0000-000000000002 = Cosmos DB Built-in Data Contributor

set -euo pipefail

COSMOS_ACCOUNT="aap-cosmos-prod"
RESOURCE_GROUP="rg-aap-prod"
SUBSCRIPTION="4c727b88-12f4-4c91-9c2b-372aab3bbae9"
ROLE_ID="00000000-0000-0000-0000-000000000002"  # Built-in Data Contributor

PRINCIPALS=(
  "ca-api-gateway-prod:69e05934-1feb-44d4-8fd2-30373f83ccec"
  "ca-orchestrator-prod:f4d7eea6-a1c9-4681-b2a2-08e32f9fe0da"
  "ca-compute-prod:d8265243-d45a-4eda-a53f-56d201778536"
  "ca-network-prod:c33a0182-a482-4842-8342-d1f7eab40e55"
  "ca-storage-prod:9dd99cd2-45ba-47b4-aa27-3999bc85421c"
  "ca-security-prod:f88d69e6-59b1-4d38-b0c8-4b5f890dc1dd"
  "ca-arc-prod:7649f118-c7ee-42f1-8508-428e301ccb07"
  "ca-sre-prod:cfb2fa91-678f-4b87-8250-617a8cc78ce8"
  "ca-web-ui-prod:aae30f33-d446-4971-911f-b0791796f638"
  "ca-teams-bot-prod:52201431-44c4-48f9-87a5-bab52c64ada0"
)

echo "Granting Cosmos DB Built-in Data Contributor to all agent identities..."
echo "Account: $COSMOS_ACCOUNT | RG: $RESOURCE_GROUP"
echo ""

for entry in "${PRINCIPALS[@]}"; do
  name="${entry%%:*}"
  principal_id="${entry##*:}"

  echo -n "  $name ($principal_id)... "

  result=$(az cosmosdb sql role assignment create \
    --account-name "$COSMOS_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --role-definition-id "$ROLE_ID" \
    --principal-id "$principal_id" \
    --scope "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DocumentDB/databaseAccounts/$COSMOS_ACCOUNT" \
    2>&1) && echo "✅ granted" || {
      if echo "$result" | grep -q "already exists\|Conflict"; then
        echo "✅ already exists"
      else
        echo "❌ FAILED"
        echo "    $result"
      fi
    }
done

echo ""
echo "Done."
