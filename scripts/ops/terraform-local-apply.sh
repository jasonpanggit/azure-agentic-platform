#!/usr/bin/env bash
# terraform-local-apply.sh — Run terraform init + apply locally with credentials.tfvars
#
# The Terraform backend (Azure Storage) requires ARM_* env vars at init time.
# credentials.tfvars cannot supply them (backend block is resolved before providers).
# This script reads credentials.tfvars and exports the required ARM_* vars.
#
# Usage:
#   bash scripts/ops/terraform-local-apply.sh [prod|staging] [extra terraform args...]
#
# Examples:
#   bash scripts/ops/terraform-local-apply.sh prod
#   bash scripts/ops/terraform-local-apply.sh prod -target=module.azure_mcp_server
#   bash scripts/ops/terraform-local-apply.sh prod -target=azurerm_role_assignment.terraform_sp_foundry_aidev

set -euo pipefail

ENV="${1:-prod}"
shift || true  # remaining args passed to terraform apply

REPO_ROOT="$(git rev-parse --show-toplevel)"
ENV_DIR="${REPO_ROOT}/terraform/envs/${ENV}"
CREDS_FILE="${ENV_DIR}/credentials.tfvars"

if [[ ! -f "$CREDS_FILE" ]]; then
  echo "ERROR: credentials.tfvars not found at ${CREDS_FILE}"
  exit 1
fi

echo "==> Reading credentials from ${CREDS_FILE}"

# Parse credentials.tfvars — match only lines that START with the exact key name
# (prevents api_gateway_client_id matching when searching for client_id)
extract() { grep -E "^${1}[[:space:]]" "$CREDS_FILE" | sed -E 's/^[^=]+=[[:space:]]*"([^"]+)".*/\1/'; }

export ARM_SUBSCRIPTION_ID="$(extract subscription_id)"
export ARM_TENANT_ID="$(extract tenant_id)"
export ARM_CLIENT_ID="$(extract client_id)"
export ARM_CLIENT_SECRET="$(extract client_secret)"

# Verify all vars are set
for var in ARM_SUBSCRIPTION_ID ARM_TENANT_ID ARM_CLIENT_ID ARM_CLIENT_SECRET; do
  if [[ -z "${!var}" ]]; then
    echo "ERROR: ${var} is empty — check credentials.tfvars"
    exit 1
  fi
done

echo "==> ARM_CLIENT_ID: ${ARM_CLIENT_ID}"
echo "==> ARM_TENANT_ID: ${ARM_TENANT_ID}"
echo "==> ARM_SUBSCRIPTION_ID: ${ARM_SUBSCRIPTION_ID}"
echo "==> ARM_CLIENT_SECRET: [set]"
echo ""

cd "$ENV_DIR"

echo "==> terraform init"
terraform init -upgrade -reconfigure

echo ""
echo "==> terraform apply -var-file=credentials.tfvars $*"
terraform apply -var-file=credentials.tfvars "$@"
