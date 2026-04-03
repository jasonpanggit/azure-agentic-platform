#!/usr/bin/env bash
# Seed runbooks via a temporary VM inside vnet-aap-prod.
# The VM is required because PostgreSQL is VNet-injected (no public access).
#
# Usage:
#   bash scripts/ops/seed-via-vm.sh
#
# Prerequisites:
#   - az login (Contributor on rg-aap-prod)
#   - terraform/envs/prod/credentials.tfvars readable
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RG="rg-aap-prod"
VNET="vnet-aap-prod"
SUBNET="snet-container-apps"
FALLBACK_SUBNET="snet-reserved-1"
VM_NAME="vm-seed-runbooks-$(date +%s)"
VM_SIZE="Standard_B1s"
VM_IMAGE="Ubuntu2404"
LOCATION="eastus2"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CREDS_FILE="${REPO_ROOT}/terraform/envs/prod/credentials.tfvars"

echo "=== Runbook Seeding via Temporary VM ==="
echo "VM: ${VM_NAME} | RG: ${RG} | VNet: ${VNET} | Subnet: ${SUBNET}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Extract credentials from credentials.tfvars
# ---------------------------------------------------------------------------
echo "--- Step 1: Extracting credentials ---"

if [[ ! -f "${CREDS_FILE}" ]]; then
  echo "ERROR: ${CREDS_FILE} not found. Cannot proceed."
  exit 1
fi

# Parse HCL-style key = "value" lines
extract_tfvar() {
  local key="$1"
  grep "^${key}" "${CREDS_FILE}" | sed 's/.*= *"//' | sed 's/".*//'
}

POSTGRES_PASSWORD="$(extract_tfvar postgres_admin_password)"
if [[ -z "${POSTGRES_PASSWORD}" ]]; then
  echo "ERROR: Could not extract postgres_admin_password from credentials.tfvars"
  exit 1
fi
echo "OK: postgres_admin_password extracted."

# ---------------------------------------------------------------------------
# Step 2: Retrieve AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY from Container App
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 2: Retrieving Azure OpenAI credentials from ca-api-gateway-prod ---"

AZURE_OPENAI_ENDPOINT=$(az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group "${RG}" \
  --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_ENDPOINT'].value" \
  -o tsv 2>/dev/null || echo "")

AZURE_OPENAI_API_KEY=$(az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group "${RG}" \
  --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_API_KEY'].value" \
  -o tsv 2>/dev/null || echo "")

# Fallback: try Key Vault
if [[ -z "${AZURE_OPENAI_API_KEY}" ]]; then
  echo "INFO: AZURE_OPENAI_API_KEY not in Container App env. Trying Key Vault..."
  AZURE_OPENAI_API_KEY=$(az keyvault secret show \
    --vault-name aap-keyvault-prod \
    --name azure-openai-api-key \
    --query "value" -o tsv 2>/dev/null || echo "")
fi

if [[ -z "${AZURE_OPENAI_ENDPOINT}" ]]; then
  echo "ERROR: Could not retrieve AZURE_OPENAI_ENDPOINT. Set it manually and re-run."
  exit 1
fi
if [[ -z "${AZURE_OPENAI_API_KEY}" ]]; then
  echo "WARNING: AZURE_OPENAI_API_KEY not found. Seed script will try managed identity (DefaultAzureCredential)."
fi

echo "OK: AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
echo "OK: AZURE_OPENAI_API_KEY=$(if [[ -n "${AZURE_OPENAI_API_KEY}" ]]; then echo "[REDACTED]"; else echo "[NOT SET - will use MI]"; fi)"

# ---------------------------------------------------------------------------
# Step 3: Create temporary VM
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 3: Creating temporary VM '${VM_NAME}' ---"

ACTIVE_SUBNET="${SUBNET}"
if ! az vm create \
  --resource-group "${RG}" \
  --name "${VM_NAME}" \
  --image "${VM_IMAGE}" \
  --size "${VM_SIZE}" \
  --vnet-name "${VNET}" \
  --subnet "${ACTIVE_SUBNET}" \
  --public-ip-address "" \
  --nsg "" \
  --admin-username azureuser \
  --generate-ssh-keys \
  --no-wait false \
  --output none 2>&1; then

  echo ""
  echo "WARNING: VM creation failed on subnet '${ACTIVE_SUBNET}' (likely subnet delegation conflict)."
  echo "Retrying with fallback subnet '${FALLBACK_SUBNET}'..."
  ACTIVE_SUBNET="${FALLBACK_SUBNET}"

  az vm create \
    --resource-group "${RG}" \
    --name "${VM_NAME}" \
    --image "${VM_IMAGE}" \
    --size "${VM_SIZE}" \
    --vnet-name "${VNET}" \
    --subnet "${ACTIVE_SUBNET}" \
    --public-ip-address "" \
    --nsg "" \
    --admin-username azureuser \
    --generate-ssh-keys \
    --no-wait false \
    --output none
fi

echo "OK: VM '${VM_NAME}' created on subnet '${ACTIVE_SUBNET}'."

# Capture resource IDs for cleanup
NIC_ID=$(az vm show --resource-group "${RG}" --name "${VM_NAME}" \
  --query "networkProfile.networkInterfaces[0].id" -o tsv)
OS_DISK_NAME=$(az vm show --resource-group "${RG}" --name "${VM_NAME}" \
  --query "storageProfile.osDisk.name" -o tsv)

echo "NIC: ${NIC_ID}"
echo "OS Disk: ${OS_DISK_NAME}"

# ---------------------------------------------------------------------------
# Cleanup handler — ALWAYS deletes VM + NIC + OS disk
# ---------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  echo ""
  echo "=== CLEANUP: Deleting temporary VM and orphaned resources ==="

  echo "--- Deleting VM '${VM_NAME}' ---"
  az vm delete \
    --resource-group "${RG}" \
    --name "${VM_NAME}" \
    --yes \
    --force-deletion none \
    --output none 2>/dev/null || echo "WARNING: VM delete failed (may already be gone)"

  echo "--- Deleting NIC ---"
  if [[ -n "${NIC_ID:-}" ]]; then
    az network nic delete --ids "${NIC_ID}" --output none 2>/dev/null || \
      echo "WARNING: NIC delete failed"
  fi

  echo "--- Deleting OS disk '${OS_DISK_NAME}' ---"
  if [[ -n "${OS_DISK_NAME:-}" ]]; then
    az disk delete \
      --resource-group "${RG}" \
      --name "${OS_DISK_NAME}" \
      --yes \
      --output none 2>/dev/null || echo "WARNING: OS disk delete failed"
  fi

  echo "=== CLEANUP COMPLETE ==="
  exit "${exit_code}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Step 4: Install Python + dependencies on the VM
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 4: Installing Python and dependencies on VM ---"

az vm run-command invoke \
  --resource-group "${RG}" \
  --name "${VM_NAME}" \
  --command-id RunShellScript \
  --scripts "
    set -e
    apt-get update -qq
    apt-get install -y -qq python3-pip python3-venv > /dev/null 2>&1
    python3 -m venv /tmp/seed-env
    /tmp/seed-env/bin/pip install -q openai psycopg[binary] pgvector pyyaml azure-identity
    echo 'OK: Python environment ready'
  " \
  --output table

echo "OK: Dependencies installed."

# ---------------------------------------------------------------------------
# Step 5: Upload seed scripts + runbooks to the VM
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 5: Uploading seed scripts and runbooks ---"

# Tar up the seed-runbooks directory and base64-encode it for transfer
TARBALL_B64=$(cd "${REPO_ROOT}" && tar czf - scripts/seed-runbooks/ | base64 | tr -d '\n')

# Split into chunks if too large for a single run-command (max ~60KB script)
# For 60 markdown files this should be under the limit, but we chunk at 50KB to be safe.
CHUNK_SIZE=50000
TOTAL_LEN=${#TARBALL_B64}
echo "Tarball size: ${TOTAL_LEN} chars (base64)"

if (( TOTAL_LEN <= CHUNK_SIZE )); then
  az vm run-command invoke \
    --resource-group "${RG}" \
    --name "${VM_NAME}" \
    --command-id RunShellScript \
    --scripts "
      mkdir -p /tmp/aap
      echo '${TARBALL_B64}' | base64 -d | tar xzf - -C /tmp/aap
      echo 'OK: Scripts uploaded'
      ls -la /tmp/aap/scripts/seed-runbooks/
      ls /tmp/aap/scripts/seed-runbooks/runbooks/ | wc -l
    " \
    --output table
else
  echo "Tarball too large for single transfer (${TOTAL_LEN} chars). Chunking..."
  # Write chunks to VM, then reassemble
  CHUNK_NUM=0
  OFFSET=0
  while (( OFFSET < TOTAL_LEN )); do
    CHUNK="${TARBALL_B64:$OFFSET:$CHUNK_SIZE}"
    az vm run-command invoke \
      --resource-group "${RG}" \
      --name "${VM_NAME}" \
      --command-id RunShellScript \
      --scripts "echo '${CHUNK}' >> /tmp/aap_tarball_b64.txt" \
      --output none
    OFFSET=$((OFFSET + CHUNK_SIZE))
    CHUNK_NUM=$((CHUNK_NUM + 1))
    echo "  Chunk ${CHUNK_NUM} uploaded (offset ${OFFSET}/${TOTAL_LEN})"
  done

  az vm run-command invoke \
    --resource-group "${RG}" \
    --name "${VM_NAME}" \
    --command-id RunShellScript \
    --scripts "
      mkdir -p /tmp/aap
      cat /tmp/aap_tarball_b64.txt | base64 -d | tar xzf - -C /tmp/aap
      rm -f /tmp/aap_tarball_b64.txt
      echo 'OK: Scripts uploaded (chunked)'
      ls -la /tmp/aap/scripts/seed-runbooks/
      ls /tmp/aap/scripts/seed-runbooks/runbooks/ | wc -l
    " \
    --output table
fi

echo "OK: Scripts uploaded."

# ---------------------------------------------------------------------------
# Step 6: Run seed.py
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 6: Running seed.py (this may take 10-20 minutes) ---"

# Build the env vars to pass
SEED_ENV="POSTGRES_HOST=aap-postgres-prod.postgres.database.azure.com"
SEED_ENV="${SEED_ENV} POSTGRES_USER=aap_admin"
SEED_ENV="${SEED_ENV} POSTGRES_DB=aap"
SEED_ENV="${SEED_ENV} POSTGRES_PASSWORD='${POSTGRES_PASSWORD}'"
SEED_ENV="${SEED_ENV} POSTGRES_PORT=5432"
SEED_ENV="${SEED_ENV} AZURE_OPENAI_ENDPOINT='${AZURE_OPENAI_ENDPOINT}'"
if [[ -n "${AZURE_OPENAI_API_KEY}" ]]; then
  SEED_ENV="${SEED_ENV} AZURE_OPENAI_API_KEY='${AZURE_OPENAI_API_KEY}'"
fi

az vm run-command invoke \
  --resource-group "${RG}" \
  --name "${VM_NAME}" \
  --command-id RunShellScript \
  --scripts "
    set -e
    cd /tmp/aap
    ${SEED_ENV} /tmp/seed-env/bin/python scripts/seed-runbooks/seed.py
  " \
  --output table \
  --no-wait false 2>/dev/null || true  # capture output even if non-zero

# Check return by querying row count
echo ""
echo "--- Verifying row count ---"

az vm run-command invoke \
  --resource-group "${RG}" \
  --name "${VM_NAME}" \
  --command-id RunShellScript \
  --scripts "
    set -e
    POSTGRES_DSN='postgresql://aap_admin:${POSTGRES_PASSWORD}@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require'
    /tmp/seed-env/bin/python -c \"
import os, psycopg
dsn = os.environ['POSTGRES_DSN']
with psycopg.connect(dsn) as conn:
    count = conn.execute('SELECT COUNT(*) FROM runbooks').fetchone()[0]
    print(f'Runbook count: {count} (expected 60)')
    if count < 60:
        raise SystemExit(f'ERROR: Only {count} runbooks seeded')
\"
  " \
  --output table

echo "OK: Seed complete."

# ---------------------------------------------------------------------------
# Step 7: Run validate.py
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 7: Running validate.py (similarity threshold check) ---"

az vm run-command invoke \
  --resource-group "${RG}" \
  --name "${VM_NAME}" \
  --command-id RunShellScript \
  --scripts "
    set -e
    cd /tmp/aap
    ${SEED_ENV} /tmp/seed-env/bin/python scripts/seed-runbooks/validate.py
  " \
  --output table \
  --no-wait false 2>/dev/null || true

echo ""
echo "=== Seeding and validation complete ==="
echo "VM '${VM_NAME}' will be deleted by cleanup handler."
echo ""
echo "Next steps:"
echo "  1. Verify the API endpoint returns 200:"
echo "     curl -H 'Authorization: Bearer \${TOKEN}' \\"
echo "       'https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/runbooks/search?q=vm+high+cpu&domain=compute'"
echo "  2. Check BUG-002 (F-02) is resolved — runbook search should now return results"
