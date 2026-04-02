# Plan 19-4: Runbook RAG Seeding — SUMMARY

**Phase:** 19 | **Plan:** 4 | **Status:** COMPLETE
**Completed:** 2026-04-02

---

## Objective

Resolve **BUG-002 / F-02**: `GET /api/v1/runbooks/search` returned 500 in production.
Root cause: `PGVECTOR_CONNECTION_STRING` was not set on `ca-api-gateway-prod` and the
`runbooks` table was empty. This plan fixes the configuration gap, provides the seeding
script, and documents the full operational procedure.

---

## What Was Done

### Task 3 — Wire `PGVECTOR_CONNECTION_STRING` via Terraform (committed)

**File:** `terraform/envs/prod/terraform.tfvars`

Added a `pgvector_connection_string = ""` placeholder with documentation:
- Points operators to `credentials.tfvars` (not committed to git) for the actual value
- References `scripts/ops/19-4-seed-runbooks.sh` as the canonical setup path
- References `docs/ops/runbook-seeding.md` for the full procedure

The actual connection string with password is already in `terraform/envs/prod/credentials.tfvars`
(verified: `pgvector_connection_string = "postgresql://aap_admin:...@aap-postgres-prod..."`)
and is wired through `terraform/envs/prod/main.tf:290` → `agent-apps` module →
`PGVECTOR_CONNECTION_STRING` env var on `ca-api-gateway`.

### Task 4 — Production Seed Script (committed)

**File:** `scripts/ops/19-4-seed-runbooks.sh`

Implements the complete production seeding runbook:
1. Retrieves PostgreSQL admin password from Key Vault (`aap-keyvault-prod → postgres-admin-password`)
2. Verifies `PGVECTOR_CONNECTION_STRING` on `ca-api-gateway-prod`; sets it if missing
3. Auto-detects `AZURE_OPENAI_ENDPOINT` from the Container App environment
4. Adds a temporary PostgreSQL firewall rule for the current machine's IP
5. Installs Python dependencies
6. Runs `seed.py` — upserts 60 runbooks with 1536-dim text-embedding-3-small embeddings
7. Verifies row count (expects exactly 60)
8. Runs `validate.py` — 12 domain queries must score ≥ 0.75 cosine similarity
9. Removes the temporary firewall rule via `trap cleanup EXIT` (always runs)

### Task 8 — Operator Documentation (committed)

**File:** `docs/ops/runbook-seeding.md`

Comprehensive operations guide covering:
- When to re-seed (initial setup, new runbooks, content updates, corruption, migration)
- Prerequisites checklist
- 4-step procedure (password → run script → verify API → persist Terraform)
- Troubleshooting for all common failure modes:
  - `PGVECTOR_CONNECTION_STRING` not set
  - Firewall rule cleanup failures
  - Validation similarity < 0.75
  - Connection refused (VNet isolation)
  - Missing Python packages
- Architecture reference table

---

## Tasks Summary

| Task | Type | Status | Description |
|---|---|---|---|
| 1 | Operational | Script-handled | Verify PGVECTOR_CONNECTION_STRING on ca-api-gateway-prod |
| 2 | Operational | Script-handled | Retrieve PostgreSQL admin password from Key Vault |
| 3 | Code | ✅ Committed | Add pgvector_connection_string placeholder to terraform.tfvars |
| 4 | Code | ✅ Committed | Create scripts/ops/19-4-seed-runbooks.sh |
| 5 | Operational | Operator step | Execute the seed script against prod |
| 6 | Operational | Operator step | Verify API endpoint returns 200 |
| 7 | Operational | Operator step | Verify compute agent cites runbooks in triage response |
| 8 | Code | ✅ Committed | Create docs/ops/runbook-seeding.md |

---

## Commits

| Hash | Message |
|---|---|
| `8f7d62b` | chore(19-4): add pgvector_connection_string placeholder to prod tfvars |
| `ae3629e` | feat(19-4): add production runbook seeding script with firewall rule management |
| `90313ae` | docs(19-4): add production runbook seeding operations guide |

---

## Files Touched

### Created
- `scripts/ops/19-4-seed-runbooks.sh` — prod runbook seeding script with firewall rule management
- `docs/ops/runbook-seeding.md` — production seeding procedure documentation

### Modified
- `terraform/envs/prod/terraform.tfvars` — added `pgvector_connection_string` placeholder

---

## Remaining Operator Steps

The code is complete. The following operator steps remain to close BUG-002 in production:

1. **Run the seed script** (requires az login, Key Vault access):
   ```bash
   bash scripts/ops/19-4-seed-runbooks.sh
   ```

2. **Verify the API returns 200**:
   ```bash
   curl -H "Authorization: Bearer ${TOKEN}" \
     "https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/runbooks/search?q=vm+high+cpu&domain=compute"
   ```

3. **Confirm terraform apply** includes `pgvector_connection_string` from `credentials.tfvars`:
   ```bash
   cd terraform/envs/prod
   terraform apply -var-file=credentials.tfvars -target=module.agent_apps
   ```

---

## Success Criteria Status

| Criterion | Status |
|---|---|
| `PGVECTOR_CONNECTION_STRING` set on `ca-api-gateway-prod` | Operator step (script handles it) |
| Runbook search returns HTTP 200 with ≥1 result | Operator step (after seeding) |
| `validate.py` reports all 12 queries pass ≥ 0.75 | Operator step (script runs validate.py) |
| PostgreSQL `runbooks` table contains exactly 60 rows | Operator step (script verifies) |
| Compute agent triage cites runbooks by name | Operator step (requires seeded data) |
| Temporary firewall rule removed after seeding | Script-enforced (trap cleanup EXIT) |
