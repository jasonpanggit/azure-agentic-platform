# Production Runbook RAG Seeding

> **Key Decision (Phase 7, Plan 07-04):** Prod seed is a manual operational step.
> The seed script is never run automatically against production.
> Staging seeding runs automatically in CI on the `apply-staging` job.

## Overview

The AAP platform uses a pgvector-enabled PostgreSQL table (`runbooks`) to power the
semantic runbook search that domain agents use during triage (TRIAGE-005). The search
endpoint is `GET /api/v1/runbooks/search`.

60 runbooks live in `scripts/seed-runbooks/runbooks/` (10 per domain × 6 domains:
compute, network, storage, security, arc, sre). This document explains how to seed
them into the production PostgreSQL database.

**Root cause of BUG-002 (F-02):** `GET /api/v1/runbooks/search` returned 500 in
production because `PGVECTOR_CONNECTION_STRING` was not set on `ca-api-gateway-prod`
and the runbooks table was empty. Plan 19-4 resolves both issues.

---

## Prerequisites

| Requirement | How to check |
|---|---|
| `az login` (active session) | `az account show` |
| Contributor on `rg-aap-prod` | `az role assignment list --assignee $(az account show --query user.name -o tsv) --scope /subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod` |
| Key Vault access (to read `postgres-admin-password`) | `az keyvault secret show --vault-name aap-keyvault-prod --name postgres-admin-password` |
| Python 3.10+ | `python3 --version` |
| `pip` | `pip --version` |
| `curl` (for IP detection) | `curl --version` |

---

## When to Re-Seed

Re-seed in these circumstances:

1. **Initial production setup** — the database has never been seeded (runbooks table empty)
2. **Adding new runbooks** — new `.md` files added to `scripts/seed-runbooks/runbooks/`
3. **Runbook content updates** — existing runbooks revised (embeddings must be regenerated)
4. **Table corruption** — the `runbooks` table is missing, truncated, or has schema drift
5. **PostgreSQL migration** — the database was restored from backup to a new server

The seed script is **idempotent**: `INSERT ... ON CONFLICT (title) DO UPDATE` means
running it multiple times is safe and will not create duplicates.

---

## Seeding Procedure

### Step 1: Set the PostgreSQL password

```bash
export POSTGRES_PASSWORD="$(az keyvault secret show \
  --vault-name aap-keyvault-prod \
  --name postgres-admin-password \
  --query value -o tsv)"
```

If the secret is not in Key Vault, retrieve from Terraform credentials:

```bash
grep postgres_admin_password terraform/envs/prod/credentials.tfvars
export POSTGRES_PASSWORD="<value>"
```

### Step 2: Run the seed script

```bash
# From repo root
bash scripts/ops/19-4-seed-runbooks.sh
```

The script will:
1. Verify `PGVECTOR_CONNECTION_STRING` is set on `ca-api-gateway-prod` (sets it if missing)
2. Auto-detect `AZURE_OPENAI_ENDPOINT` from the Container App environment
3. Add a temporary PostgreSQL firewall rule for the current machine's IP
4. Install Python dependencies from `scripts/seed-runbooks/requirements.txt`
5. Run `seed.py` — upserts 60 runbooks with 1536-dim embeddings
6. Verify the row count (expects exactly 60)
7. Run `validate.py` — 12 domain queries must all score ≥ 0.75 cosine similarity
8. Remove the temporary firewall rule (always runs via `trap cleanup EXIT`)

**Expected output:**

```
=== Phase 19-4: Production Runbook RAG Seeding ===
OK: PGVECTOR_CONNECTION_STRING is already set.
OK: Firewall rule 'temp-seed-20260402123456' added for 1.2.3.4.
Found 60 runbook files
Connecting to PostgreSQL...
  Processing: compute-01-vm-high-cpu (compute)
  ...
Done: 60 inserted, 0 updated, 60 total

OK: runbooks table contains 60 rows (expected 60)

Validating 60 runbooks across 6 domains
  [PASS] compute: "VM is experiencing high CPU utilization..." -> compute-01-vm-high-cpu (sim=0.8200)
  ...
All runbooks pass similarity threshold validation!

=== Seeding complete ===
```

### Step 3: Verify the API endpoint

After seeding, confirm the search endpoint returns HTTP 200:

```bash
# Get an auth token (if Entra auth is enabled)
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/abbdca26-d233-4a1e-9d8c-c4eebbc16e50/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=api://505df1d3-3bd3-4151-ae87-6e5974b72a44/.default" \
  | jq -r '.access_token')

API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

# Test: compute domain search
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${API_URL}/api/v1/runbooks/search?q=vm+high+cpu&domain=compute" \
  -w "\nHTTP: %{http_code}\n"
```

Expected response: `HTTP: 200` with `runbooks` array containing at least 1 result.

### Step 4: Persist the connection string in Terraform

The `PGVECTOR_CONNECTION_STRING` must also be in `terraform/envs/prod/credentials.tfvars`
so it survives the next `terraform apply` without being wiped:

```
# In terraform/envs/prod/credentials.tfvars (not committed to git):
pgvector_connection_string = "postgresql://aap_admin:<password>@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require"
```

Verify the variable is wired:

```bash
grep pgvector_connection_string terraform/envs/prod/credentials.tfvars
```

---

## Troubleshooting

### `PGVECTOR_CONNECTION_STRING` not set on `ca-api-gateway-prod`

Set it manually:

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars "PGVECTOR_CONNECTION_STRING=postgresql://aap_admin:<password>@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require"
```

### Firewall rule not cleaned up

If the script exits abnormally and the firewall rule persists:

```bash
az postgres flexible-server firewall-rule list \
  --resource-group rg-aap-prod \
  --name aap-postgres-prod \
  --query "[?starts_with(name, 'temp-seed-')]" \
  -o table

# Delete each temp-seed-* rule:
az postgres flexible-server firewall-rule delete \
  --resource-group rg-aap-prod \
  --name aap-postgres-prod \
  --rule-name <rule-name> \
  --yes
```

### Validation queries fail (similarity < 0.75)

Possible causes:

1. **Wrong embedding model deployment** — `seed.py` uses `text-embedding-3-small`.
   Verify the model is deployed on the Foundry account:
   ```bash
   az cognitiveservices account deployment list \
     --name aap-foundry-prod \
     --resource-group rg-aap-prod \
     --query "[?name=='text-embedding-3-small']" \
     -o table
   ```

2. **Embeddings generated against a different model** — Re-seed with the correct endpoint.

3. **Low similarity threshold** — Edit `scripts/seed-runbooks/validate.py` and lower
   `SIMILARITY_THRESHOLD` temporarily to diagnose (default 0.75 is intentionally strict).

4. **IVFFlat index not built** — The index is created by `ensure_table()` but requires
   enough rows to build. If the table was empty when the index was created, VACUUM and
   recreate:
   ```sql
   DROP INDEX IF EXISTS idx_runbooks_embedding;
   CREATE INDEX idx_runbooks_embedding ON runbooks
     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
   ANALYZE runbooks;
   ```

### `psycopg.OperationalError: connection refused`

The PostgreSQL server is VNet-injected. The firewall rule must be in place and the
script must run from a machine with a public IP. Check:
- Firewall rule was created: `az postgres flexible-server firewall-rule list ...`
- Your IP matches the rule's start/end IP
- Port 5432 is not blocked by a local firewall

### `ModuleNotFoundError: No module named 'pgvector'`

```bash
pip install -r scripts/seed-runbooks/requirements.txt
```

---

## Architecture Reference

| Component | Value |
|---|---|
| PostgreSQL server | `aap-postgres-prod.postgres.database.azure.com` |
| Database | `aap` |
| Username | `aap_admin` |
| Table | `runbooks` |
| Vector extension | `pgvector` (vector dimension: 1536) |
| Embedding model | `text-embedding-3-small` (Azure OpenAI) |
| Container App env var | `PGVECTOR_CONNECTION_STRING` on `ca-api-gateway-prod` |
| Runbook count | 60 (10 per domain × 6 domains) |
| Similarity threshold | ≥ 0.75 cosine similarity |
| API endpoint | `GET /api/v1/runbooks/search?q=<query>&domain=<domain>` |

---

## Related Files

| File | Purpose |
|---|---|
| `scripts/seed-runbooks/seed.py` | Idempotent seed script (reads runbooks, generates embeddings, upserts) |
| `scripts/seed-runbooks/validate.py` | Post-seed validation (12 domain queries, threshold 0.75) |
| `scripts/seed-runbooks/requirements.txt` | Python dependencies for seed + validate |
| `scripts/seed-runbooks/runbooks/` | 60 runbook `.md` files with YAML frontmatter |
| `scripts/ops/19-4-seed-runbooks.sh` | Production seeding script with firewall rule management |
| `services/api-gateway/runbooks.py` | API gateway runbook search handler |
| `terraform/modules/agent-apps/main.tf` | Wires `PGVECTOR_CONNECTION_STRING` to `ca-api-gateway` |
| `terraform/envs/prod/credentials.tfvars` | Stores `pgvector_connection_string` (not committed to git) |
