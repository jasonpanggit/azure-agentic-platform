#!/usr/bin/env bash
set -euo pipefail

# Bootstrap Terraform state storage accounts for AAP
# Run this script ONCE per environment before terraform init.
#
# Prerequisites:
#   - Azure CLI authenticated (`az login`)
#   - Permissions to create resource groups and storage accounts
#   - AZURE_SUBSCRIPTION_ID set or passed as argument
#
# Usage:
#   ./scripts/bootstrap-state.sh [subscription_id]

SUBSCRIPTION_ID="${1:-${AZURE_SUBSCRIPTION_ID:-}}"
LOCATION="eastus2"
PROJECT="aap"

if [[ -z "$SUBSCRIPTION_ID" ]]; then
  echo "ERROR: Pass subscription_id as argument or set AZURE_SUBSCRIPTION_ID"
  exit 1
fi

az account set --subscription "$SUBSCRIPTION_ID"

for env in dev stg prod; do
  RG_NAME="rg-${PROJECT}-tfstate-${env}"
  SA_NAME="st${PROJECT}tfstate${env}"
  CONTAINER_NAME="tfstate"

  echo "=== Bootstrapping state backend for environment: ${env} ==="

  # Create resource group
  az group create \
    --name "$RG_NAME" \
    --location "$LOCATION" \
    --tags environment="$env" managed-by=script project="$PROJECT"

  # Create storage account (no public blob access, TLS 1.2, Entra auth only)
  az storage account create \
    --name "$SA_NAME" \
    --resource-group "$RG_NAME" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --allow-blob-public-access false \
    --min-tls-version TLS1_2 \
    --allow-shared-key-access false \
    --tags environment="$env" managed-by=script project="$PROJECT"

  # Create blob container for tfstate
  az storage container create \
    --name "$CONTAINER_NAME" \
    --account-name "$SA_NAME" \
    --auth-mode login

  echo "  Created: ${SA_NAME}/${CONTAINER_NAME}"
done

echo ""
echo "=== Bootstrap complete ==="
echo "Next steps:"
echo "  1. Grant GitHub Actions service principal 'Storage Blob Data Contributor' on each storage account"
echo "  2. Configure federated credentials for OIDC in the App Registration"
echo "  3. Run 'terraform init' in each envs/<env>/ directory"
