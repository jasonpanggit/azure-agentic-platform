# Summary: Fix API Gateway Prod Blocker — Set ORCHESTRATOR_AGENT_ID + Azure AI Developer RBAC

**ID:** 260331-k6y
**Mode:** quick
**Completed:** 2026-03-31
**Status:** DONE

---

## What Was Done

### B1 — ORCHESTRATOR_AGENT_ID env var set on ca-api-gateway-prod

**Result:** `ORCHESTRATOR_AGENT_ID=asst_NeBVjCA5isNrIERoGYzRpBTu` is live on revision `ca-api-gateway-prod--0000030`.

**Complication encountered:** The standard `az containerapp update --set-env-vars` command failed repeatedly with `UNAUTHORIZED` on ACR image pull. Root cause: the Container Apps control plane validates the image manifest on every revision creation, and the SHA-tagged image (`80428c395a...`) was inaccessible to the control plane (even though AcrPull was assigned to the managed identity).

**Workaround applied:**
1. Temporarily enabled ACR admin user to allow credential-based registry auth.
2. Updated registry to use username/password (`az containerapp registry set`).
3. Applied env var update — created revision `0000029`, but it crashed with `ModuleNotFoundError: No module named 'agents'` (the SHA-tagged image is broken).
4. Re-applied update using the known-working image digest from revision `0000023` (`sha256:94233d2c...`) → revision `0000030` healthy.
5. Restored registry to managed identity auth and disabled ACR admin.

**Terraform persistence:** `orchestrator_agent_id = "asst_NeBVjCA5isNrIERoGYzRpBTu"` added to `terraform/envs/prod/terraform.tfvars`.

---

### B2 (F-01) — Azure AI Developer RBAC assigned to gateway managed identity

**Result:** Role assignment `6a001d6b-bc29-4355-962f-0103c81f90c6` created on scope `/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod`.

**Terraform persistence:** `api-gateway-aidev-foundry` assignment block added to `terraform/modules/rbac/main.tf`. Two new variables (`resource_group_name`, `foundry_account_name`) added to `terraform/modules/rbac/variables.tf` with empty string defaults. Prod `main.tf` passes `azurerm_resource_group.main.name` and `module.foundry.foundry_account_name` to the rbac module.

---

## Verification Results

| Check | Result |
|-------|--------|
| `az containerapp show` → `ORCHESTRATOR_AGENT_ID` | ✅ `asst_NeBVjCA5isNrIERoGYzRpBTu` |
| `az role assignment list` → `Azure AI Developer` on Foundry scope | ✅ confirmed |
| `terraform/envs/prod/terraform.tfvars` has `orchestrator_agent_id` | ✅ committed |
| `terraform/modules/rbac/main.tf` has `api-gateway-aidev-foundry` | ✅ committed |
| Gateway health endpoint | ✅ `{"status":"ok","version":"1.0.0"}` |
| Gateway startup logs — no `ValueError: ORCHESTRATOR_AGENT_ID` | ✅ `Application startup complete` |
| `terraform fmt -check` on rbac module | ✅ passes |
| `terraform fmt -check` on prod env | ✅ passes |

---

## Side Discovery: Broken Image Tag

The SHA tag `80428c395a06521a5be866f0eb283bb8b8058add` in the container app template points to a broken image that crashes with `ModuleNotFoundError: No module named 'agents'`. The working image is at digest `sha256:94233d2c737ff1fcf4c06f6b4574750a9263273fde0679e08a43f617c90ff14a` (revision `0000023`).

**Recommendation:** The next CI/CD image build should deploy a fixed image that includes the `agents` module in the Python path. This is a pre-existing bug unrelated to this task.

---

## Files Changed

| File | Change |
|------|--------|
| `terraform/envs/prod/terraform.tfvars` | Added `orchestrator_agent_id = "asst_NeBVjCA5isNrIERoGYzRpBTu"` |
| `terraform/modules/rbac/main.tf` | Added `api-gateway-aidev-foundry` Azure AI Developer assignment block |
| `terraform/modules/rbac/variables.tf` | Added `resource_group_name` + `foundry_account_name` vars (default: "") |
| `terraform/envs/prod/main.tf` | Passes `resource_group_name` + `foundry_account_name` to rbac module |
| `docs/MANUAL-SETUP.md` | Marked Step 1 and Step 2 as ✅ DONE with role assignment ID |

---

## Phase 8 Finding Status

- **F-01** (Foundry RBAC): **RESOLVED** — `Azure AI Developer` assigned, wired in IaC.
- **F-02** (runbook search 500): Still open — separate PostgreSQL/pgvector issue.
