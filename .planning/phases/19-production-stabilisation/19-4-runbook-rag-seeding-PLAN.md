---
phase: 19
plan: 4
title: "Runbook RAG Seeding"
objective: "Fix the runbook search 500 error in production by verifying the PGVECTOR_CONNECTION_STRING env var, seeding the PostgreSQL pgvector store with the 60 existing runbooks, and wiring the runbook retrieval into the compute agent's diagnostic flow."
wave: 3
estimated_tasks: 8
gap_closure: false
---

# Plan 19-4: Runbook RAG Seeding

## Objective

Resolve **BUG-002 / F-02**: `GET /api/v1/runbooks/search` returns 500 in production. Runbook-assisted triage is completely non-functional. This plan fixes the connection string configuration, seeds the prod PostgreSQL pgvector store with the 60 runbooks already present in the repository, validates semantic search quality, and confirms the compute agent's diagnostic flow cites relevant runbooks in triage responses.

## Context

**Current state (verified from research):**

- **60 runbooks exist** in `scripts/seed-runbooks/runbooks/` (10 per domain × 6 domains)
- **`seed.py`** is fully functional: reads YAML frontmatter, generates 1536-dim embeddings via Azure OpenAI `text-embedding-3-small`, upserts with `ON CONFLICT (title) DO UPDATE`
- **`validate.py`** runs 12 domain queries with `SIMILARITY_THRESHOLD=0.75`
- **Root cause of 500:** `PGVECTOR_CONNECTION_STRING` is either not set or set incorrectly on `ca-api-gateway-prod`
- **Terraform already passes `pgvector_connection_string`** to agent-apps module (line 268 of `terraform/envs/prod/main.tf`) — the variable may be empty in `terraform.tfvars`

**Key constraint from research:** Prod seed is a **manual operational step** (established in Phase 7, Plan 07-04, Key Decision: "Prod seed is manual operational step — Never run seed script against prod automatically"). This plan follows that pattern: seed script uses a temporary PostgreSQL firewall rule pattern, always cleaned up.

**Key constraint:** The PostgreSQL server is VNet-injected. GitHub Actions runners and developer machines cannot reach it directly. The temporary firewall rule pattern (used since Phase 1, Plan 1-05) must be used.

**PROD requirement:** TRIAGE-005 — Runbook library stored in PostgreSQL with pgvector; agents retrieve top-3 semantically relevant runbooks via vector search and cite them in triage responses.

---

## Tasks

### Task 1: Verify `PGVECTOR_CONNECTION_STRING` on `ca-api-gateway-prod`

```bash
az containerapp show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --query "properties.template.containers[0].env[?name=='PGVECTOR_CONNECTION_STRING']" \
  -o json
```

**If the env var is not set or empty**, it means the Terraform variable was never populated. Check:

```bash
grep -n "pgvector_connection_string\|PGVECTOR" terraform/envs/prod/terraform.tfvars
```

If missing from tfvars, this is the root cause.

### Task 2: Retrieve the PostgreSQL admin password

The seed script needs the admin password to connect to PostgreSQL with a temporary firewall rule (not managed identity, which requires Entra token refresh in `psycopg`).

Retrieve from Key Vault:
```bash
az keyvault secret show \
  --vault-name aap-keyvault-prod \
  --name postgres-admin-password \
  --query "value" -o tsv
```

If not in Key Vault, check Terraform state output:
```bash
cd terraform/envs/prod
terraform output postgres_admin_password 2>/dev/null || echo "Not in Terraform outputs"
```

Store the password securely in a local env var for the seeding session:
```bash
export POSTGRES_PASSWORD="<retrieved-password>"
```

### Task 3: Set `PGVECTOR_CONNECTION_STRING` on `ca-api-gateway-prod`

Build the connection string and set it on the Container App:

```bash
POSTGRES_HOST="aap-postgres-prod.postgres.database.azure.com"
POSTGRES_USER="aap_admin"
POSTGRES_DB="aap"
POSTGRES_PORT="5432"

# DSN format expected by services/api-gateway/runbooks.py
CONNECTION_STRING="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}?sslmode=require"

az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "PGVECTOR_CONNECTION_STRING=${CONNECTION_STRING}"
```

**Also wire into Terraform** to prevent the value from being lost on the next `terraform apply`:

In `terraform/envs/prod/terraform.tfvars`, add:
```hcl
pgvector_connection_string = "postgresql://aap_admin:${POSTGRES_PASSWORD}@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require"
```

> **Security note:** The password in tfvars should reference a Key Vault secret reference, not be hardcoded. Check if the agent-apps module supports Key Vault secret references for this var. If not, use the `az containerapp update --set-env-vars` approach and document as a manual step.

### Task 4: Set up seed environment with temporary PostgreSQL firewall rule

```bash
#!/usr/bin/env bash
# Save as scripts/ops/19-4-seed-runbooks.sh

set -euo pipefail

RESOURCE_GROUP="rg-aap-prod"
POSTGRES_SERVER="aap-postgres-prod"
FIREWALL_RULE="temp-seed-$(date +%Y%m%d%H%M%S)"

# Get runner IP
MY_IP=$(curl -s https://ifconfig.me)
echo "Runner IP: $MY_IP"

# Add temporary firewall rule
echo "Adding temporary firewall rule..."
az postgres flexible-server firewall-rule create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$POSTGRES_SERVER" \
  --rule-name "$FIREWALL_RULE" \
  --start-ip-address "$MY_IP" \
  --end-ip-address "$MY_IP"

cleanup() {
  echo "Removing temporary firewall rule..."
  az postgres flexible-server firewall-rule delete \
    --resource-group "$RESOURCE_GROUP" \
    --name "$POSTGRES_SERVER" \
    --rule-name "$FIREWALL_RULE" \
    --yes || echo "WARNING: Failed to remove firewall rule $FIREWALL_RULE — remove manually"
}

# Always clean up, even on failure
trap cleanup EXIT

echo "Firewall rule added. Running seed..."

# Set required env vars
export POSTGRES_DSN="postgresql://aap_admin:${POSTGRES_PASSWORD}@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require"
export AZURE_OPENAI_ENDPOINT="https://aap-foundry-prod.openai.azure.com/"
export AZURE_OPENAI_API_VERSION="2024-02-01"

# Run seed from repo root
cd "$(git rev-parse --show-toplevel)"
pip install -r scripts/seed-runbooks/requirements.txt -q
python scripts/seed-runbooks/seed.py

echo "Seed complete. Running validation..."
python scripts/seed-runbooks/validate.py

echo "Validation complete. Cleanup will run on exit."
```

### Task 5: Execute the seed script

```bash
# From repo root
chmod +x scripts/ops/19-4-seed-runbooks.sh

# Set the password (from Task 2)
export POSTGRES_PASSWORD="<retrieved-password>"

# Run seed (firewall rule is added and removed automatically by trap)
bash scripts/ops/19-4-seed-runbooks.sh
```

**Expected output from `seed.py`:**
```
Seeding runbooks...
  ✓ compute-01-vm-high-cpu (domain: compute)
  ✓ compute-02-vm-disk-full (domain: compute)
  ... (60 total)
Seeding complete: 60 runbooks upserted.
```

**Expected output from `validate.py`:**
```
Running validation queries...
  compute: "vm high cpu"          → score=0.82 ✓
  compute: "disk full"            → score=0.79 ✓
  network: "nsg rule conflict"    → score=0.81 ✓
  security: "unauthorized access" → score=0.76 ✓
  arc: "server disconnected"      → score=0.85 ✓
  sre: "deployment rollback"      → score=0.77 ✓
  ... (12 total)
All 12 validation queries pass (threshold: 0.75).
```

### Task 6: Verify the API endpoint returns 200 in production

After seeding, test the runbook search endpoint:

```bash
# Get auth token (if auth is enabled from Plan 2)
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/abbdca26-d233-4a1e-9d8c-c4eebbc16e50/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=api://505df1d3-3bd3-4151-ae87-6e5974b72a44/.default" \
  | jq -r '.access_token')

API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

# Test 1: Basic compute domain search
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${API_URL}/api/v1/runbooks/search?q=vm+high+cpu&domain=compute" \
  -w "\nHTTP: %{http_code}\n" | jq '{count: (.runbooks | length), first: (.runbooks[0].title // "none")}'

# Test 2: Security domain search
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${API_URL}/api/v1/runbooks/search?q=unauthorized+access+alert&domain=security" \
  -w "\nHTTP: %{http_code}\n" | jq '{count: (.runbooks | length), first: (.runbooks[0].title // "none")}'

# Test 3: Arc domain search
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${API_URL}/api/v1/runbooks/search?q=arc+server+disconnected&domain=arc" \
  -w "\nHTTP: %{http_code}\n" | jq '{count: (.runbooks | length), first: (.runbooks[0].title // "none")}'
```

All three tests must return `HTTP: 200` and `count > 0`.

### Task 7: Verify compute agent cites runbooks in diagnostic flow

The compute agent's diagnostic flow (in `agents/compute/agent.py`) should already call runbook search as part of triage. Confirm by triggering a synthetic compute incident:

```bash
# Inject a synthetic high-CPU incident
curl -s -X POST "${API_URL}/api/v1/incidents" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "test-runbook-rag-01",
    "severity": "Sev2",
    "domain": "compute",
    "affected_resources": ["/subscriptions/4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-test-01"],
    "detection_rule": "CPU_ALERT_HIGH",
    "kql_evidence": "avg_cpu_percent > 95 for 15 minutes"
  }'

# Poll the SSE stream for the incident response
# The response should mention a runbook by name (e.g., "compute-01-vm-high-cpu")
```

Check Application Insights for runbook retrieval spans:
```kql
dependencies
| where cloud_RoleName == "ca-api-gateway-prod"
| where name == "runbook.search"
| where timestamp > ago(30m)
| project timestamp, name, success, resultCode, data
| order by timestamp desc
| take 10
```

### Task 8: Document the prod seeding procedure

Create `docs/ops/runbook-seeding.md` documenting the production runbook seeding procedure. This satisfies the "Prod seed is manual operational step" key decision from Phase 7.

Contents should include:
- When to re-seed (adding new runbooks, or if the table is corrupted)
- Prerequisites (Key Vault password access, Azure CLI auth)
- Exact commands (reference `scripts/ops/19-4-seed-runbooks.sh`)
- How to verify the seed succeeded
- What to do if validation queries fail (lower similarity thresholds, check embedding model deployment)

---

## Success Criteria

1. `curl -H "Authorization: Bearer ${TOKEN}" "${API_URL}/api/v1/runbooks/search?q=vm+high+cpu&domain=compute"` returns `HTTP 200` with at least 1 runbook result
2. `validate.py` reports all 12 domain queries pass with score ≥ 0.75
3. `PGVECTOR_CONNECTION_STRING` env var is set (non-empty) on `ca-api-gateway-prod`: `az containerapp show --name ca-api-gateway-prod ... --query "properties.template.containers[0].env[?name=='PGVECTOR_CONNECTION_STRING']"` returns a non-empty value
4. PostgreSQL `runbooks` table contains exactly 60 rows: `SELECT COUNT(*) FROM runbooks;` returns `60`
5. Compute agent triage response for a synthetic CPU incident cites at least one runbook by name (confirmed by SSE stream content or Application Insights logs)
6. Temporary PostgreSQL firewall rule is removed after seeding (confirmed by `az postgres flexible-server firewall-rule list --name aap-postgres-prod` — no `temp-seed-*` rules)

---

## Files Touched

### Created
- `scripts/ops/19-4-seed-runbooks.sh` — prod runbook seeding script with firewall rule management
- `docs/ops/runbook-seeding.md` — production seeding procedure documentation

### Modified
- `terraform/envs/prod/terraform.tfvars` — add `pgvector_connection_string` value (if using Terraform for env var management)
