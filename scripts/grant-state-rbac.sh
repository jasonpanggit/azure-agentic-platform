#!/usr/bin/env bash
set -euo pipefail

# Grant Storage Blob Data Contributor to the Terraform service principal
# on all AAP state storage accounts.
#
# MUST be run by a user/SP with Owner or User Access Administrator role.
#
# Usage:
#   az login  # as Owner
#   ./scripts/grant-state-rbac.sh <terraform_sp_client_id> [subscription_id]
#
# Example:
#   ./scripts/grant-state-rbac.sh 65cf695c-1def-48ba-96af-d968218c90ba 4c727b88-xxxx-xxxx-xxxx-xxxxxxxxxxxx

SP_CLIENT_ID="${1:-}"
SUBSCRIPTION_ID="${2:-${AZURE_SUBSCRIPTION_ID:-}}"
PROJECT="aap"

if [[ -z "$SP_CLIENT_ID" ]]; then
  echo "ERROR: Pass the Terraform service principal client_id as first argument"
  echo "Usage: $0 <sp_client_id> [subscription_id]"
  exit 1
fi

if [[ -z "$SUBSCRIPTION_ID" ]]; then
  SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
  echo "Using current subscription: $SUBSCRIPTION_ID"
fi

az account set --subscription "$SUBSCRIPTION_ID"

# Resolve SP object ID from client ID
SP_OBJECT_ID="$(az ad sp show --id "$SP_CLIENT_ID" --query id -o tsv)"
echo "Service Principal: $SP_CLIENT_ID (object: $SP_OBJECT_ID)"
echo ""

for env in dev stg prod; do
  SA_NAME="st${PROJECT}tfstate${env}"
  RG_NAME="rg-${PROJECT}-tfstate-${env}"

  # Check if storage account exists
  SA_ID="$(az storage account show --name "$SA_NAME" --resource-group "$RG_NAME" --query id -o tsv 2>/dev/null || true)"
  if [[ -z "$SA_ID" ]]; then
    echo "  SKIP: ${SA_NAME} does not exist (run bootstrap-state.sh first)"
    continue
  fi

  echo "  Granting Storage Blob Data Contributor on ${SA_NAME}..."
  az role assignment create \
    --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Contributor" \
    --scope "$SA_ID" \
    --output none 2>/dev/null && echo "    Done." || echo "    Already assigned or insufficient permissions."
done

echo ""
echo "RBAC grants complete. Terraform can now use 'use_azuread_auth = true' for state backend."
echo "Run 'terraform init' in each envs/<env>/ directory to verify."
