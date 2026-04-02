#!/usr/bin/env bash
# Phase 19 Plan 4: Production Runbook RAG Seeding
#
# Seeds the PostgreSQL pgvector store with the 60 runbooks in scripts/seed-runbooks/runbooks/
# using a temporary firewall rule pattern (PostgreSQL is VNet-injected and not directly
# reachable from developer machines or GitHub Actions runners).
#
# This is a MANUAL OPERATIONAL STEP — never run automatically against prod.
# See docs/ops/runbook-seeding.md for full procedure and troubleshooting guidance.
#
# Prerequisites:
#   - az login (user or SP with Contributor on rg-aap-prod + Key Vault reader)
#   - POSTGRES_PASSWORD env var set (retrieve from Key Vault — see Task 2 below)
#   - Python 3.10+ with pip
#   - curl (for IP detection)
#
# Usage:
#   export POSTGRES_PASSWORD="$(az keyvault secret show --vault-name aap-keyvault-prod \
#     --name postgres-admin-password --query value -o tsv)"
#   bash scripts/ops/19-4-seed-runbooks.sh
#
# Environment variables (optional overrides):
#   POSTGRES_HOST     — default: aap-postgres-prod.postgres.database.azure.com
#   POSTGRES_USER     — default: aap_admin
#   POSTGRES_DB       — default: aap
#   POSTGRES_PORT     — default: 5432
#   AZURE_OPENAI_ENDPOINT — auto-detected from Container App env if unset
#   SKIP_VALIDATE     — set to "1" to skip post-seed validation

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-aap-prod"
POSTGRES_SERVER="aap-postgres-prod"
FIREWALL_RULE="temp-seed-$(date +%Y%m%d%H%M%S)"

POSTGRES_HOST="${POSTGRES_HOST:-aap-postgres-prod.postgres.database.azure.com}"
POSTGRES_USER="${POSTGRES_USER:-aap_admin}"
POSTGRES_DB="${POSTGRES_DB:-aap}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "=== Phase 19-4: Production Runbook RAG Seeding ==="
echo ""

# ---------------------------------------------------------------------------
# Task 2: Retrieve POSTGRES_PASSWORD if not already set
# ---------------------------------------------------------------------------
if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "--- Retrieving PostgreSQL admin password from Key Vault ---"
  POSTGRES_PASSWORD=$(az keyvault secret show \
    --vault-name aap-keyvault-prod \
    --name postgres-admin-password \
    --query "value" -o tsv 2>/dev/null || echo "")

  if [[ -z "${POSTGRES_PASSWORD}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD not set and Key Vault retrieval failed."
    echo ""
    echo "Retrieve manually and set before running:"
    echo "  export POSTGRES_PASSWORD=\"\$(az keyvault secret show \\"
    echo "    --vault-name aap-keyvault-prod \\"
    echo "    --name postgres-admin-password \\"
    echo "    --query value -o tsv)\""
    echo ""
    echo "Or check Terraform state:"
    echo "  cd terraform/envs/prod"
    echo "  terraform output postgres_admin_password 2>/dev/null"
    exit 1
  fi
  echo "OK: Password retrieved from Key Vault."
fi

# ---------------------------------------------------------------------------
# Task 1: Verify PGVECTOR_CONNECTION_STRING on ca-api-gateway-prod
# ---------------------------------------------------------------------------
echo ""
echo "--- Task 1: Verify PGVECTOR_CONNECTION_STRING on ca-api-gateway-prod ---"
PGVECTOR_VALUE=$(az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group "${RESOURCE_GROUP}" \
  --query "properties.template.containers[0].env[?name=='PGVECTOR_CONNECTION_STRING'].value" \
  -o tsv 2>/dev/null || echo "")

if [[ -z "${PGVECTOR_VALUE}" ]]; then
  echo "WARNING: PGVECTOR_CONNECTION_STRING is not set on ca-api-gateway-prod."
  echo "Setting it now..."

  CONNECTION_STRING="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}?sslmode=require"

  az containerapp update \
    --name ca-api-gateway-prod \
    --resource-group "${RESOURCE_GROUP}" \
    --set-env-vars "PGVECTOR_CONNECTION_STRING=${CONNECTION_STRING}" \
    --output none

  echo "OK: PGVECTOR_CONNECTION_STRING set on ca-api-gateway-prod."
  echo ""
  echo "NOTE: Also add to terraform/envs/prod/terraform.tfvars to persist across terraform apply:"
  echo "  pgvector_connection_string = \"<connection-string>\""
  echo "  (Use credentials.tfvars to store the actual value — do not hardcode password in terraform.tfvars)"
else
  echo "OK: PGVECTOR_CONNECTION_STRING is already set."
fi

# ---------------------------------------------------------------------------
# Resolve Azure OpenAI endpoint from api-gateway Container App if not set
# ---------------------------------------------------------------------------
if [[ -z "${AZURE_OPENAI_ENDPOINT:-}" ]]; then
  echo ""
  echo "--- Detecting AZURE_OPENAI_ENDPOINT from ca-api-gateway-prod ---"
  AZURE_OPENAI_ENDPOINT=$(az containerapp show \
    --name ca-api-gateway-prod \
    --resource-group "${RESOURCE_GROUP}" \
    --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_ENDPOINT'].value" \
    -o tsv 2>/dev/null || echo "")

  if [[ -z "${AZURE_OPENAI_ENDPOINT}" ]]; then
    echo "WARNING: Could not auto-detect AZURE_OPENAI_ENDPOINT."
    echo "Set it explicitly:"
    echo "  export AZURE_OPENAI_ENDPOINT=\"https://aap-foundry-prod.openai.azure.com/\""
    exit 1
  fi
  echo "OK: AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
fi

export AZURE_OPENAI_ENDPOINT

# ---------------------------------------------------------------------------
# Task 4: Set up temporary PostgreSQL firewall rule
# ---------------------------------------------------------------------------
echo ""
echo "--- Task 4: Adding temporary firewall rule ---"

MY_IP=$(curl -s https://ifconfig.me 2>/dev/null || curl -s https://api.ipify.org 2>/dev/null || echo "")
if [[ -z "${MY_IP}" ]]; then
  echo "ERROR: Could not detect public IP address. Check internet connectivity."
  exit 1
fi
echo "Runner IP: ${MY_IP}"

az postgres flexible-server firewall-rule create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${POSTGRES_SERVER}" \
  --rule-name "${FIREWALL_RULE}" \
  --start-ip-address "${MY_IP}" \
  --end-ip-address "${MY_IP}" \
  --output none

echo "OK: Firewall rule '${FIREWALL_RULE}' added for ${MY_IP}."

# Register cleanup handler — always removes the temporary firewall rule on exit.
cleanup() {
  local exit_code=$?
  echo ""
  echo "--- Cleanup: removing temporary firewall rule '${FIREWALL_RULE}' ---"
  az postgres flexible-server firewall-rule delete \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${POSTGRES_SERVER}" \
    --rule-name "${FIREWALL_RULE}" \
    --yes \
    --output none 2>/dev/null || \
    echo "WARNING: Failed to remove firewall rule '${FIREWALL_RULE}'. Remove it manually:"
    echo "  az postgres flexible-server firewall-rule delete \\"
    echo "    --resource-group ${RESOURCE_GROUP} \\"
    echo "    --name ${POSTGRES_SERVER} \\"
    echo "    --rule-name ${FIREWALL_RULE} --yes"
  exit "${exit_code}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Task 5: Install dependencies and run seed
# ---------------------------------------------------------------------------
echo ""
echo "--- Task 5: Installing seed dependencies ---"
pip install -r "${REPO_ROOT}/scripts/seed-runbooks/requirements.txt" -q

echo ""
echo "--- Task 5: Running seed.py ---"
export POSTGRES_DSN="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}?sslmode=require"

cd "${REPO_ROOT}"
python scripts/seed-runbooks/seed.py

echo ""
echo "--- Seed complete. Verifying row count ---"
python - <<PYEOF
import os
import psycopg

dsn = os.environ["POSTGRES_DSN"]
with psycopg.connect(dsn) as conn:
    count = conn.execute("SELECT COUNT(*) FROM runbooks").fetchone()[0]
    print(f"OK: runbooks table contains {count} rows (expected 60)")
    if count != 60:
        print(f"WARNING: Expected 60 rows, got {count}.")
PYEOF

# ---------------------------------------------------------------------------
# Task 6: Post-seed validation
# ---------------------------------------------------------------------------
if [[ "${SKIP_VALIDATE:-0}" == "1" ]]; then
  echo ""
  echo "--- Skipping validation (SKIP_VALIDATE=1) ---"
else
  echo ""
  echo "--- Running validate.py (similarity threshold >= 0.75) ---"
  python scripts/seed-runbooks/validate.py
fi

echo ""
echo "=== Seeding complete ==="
echo ""
echo "Next steps:"
echo "  1. Verify the API endpoint returns 200:"
echo "     curl -H \"Authorization: Bearer \${TOKEN}\" \\"
echo "       \"https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/runbooks/search?q=vm+high+cpu&domain=compute\""
echo "     Expected: HTTP 200, count > 0"
echo ""
echo "  2. Check PGVECTOR_CONNECTION_STRING is set in terraform.tfvars (credentials.tfvars)"
echo "     grep pgvector_connection_string terraform/envs/prod/credentials.tfvars"
echo ""
echo "  3. See docs/ops/runbook-seeding.md for full troubleshooting guide"
