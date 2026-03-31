# Terraform Drift Fix — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Goal:** Bring all Azure-provisioned resources under full Terraform management so the entire platform can be rebuilt from scratch with `terraform apply` (plus two documented one-time manual steps).

---

## Problem Statement

A drift audit identified resources provisioned manually in Azure that are either absent from Terraform state, referenced only as input variables, or suppressed via `ignore_changes` blocks. The result is that `terraform apply` from a clean state would produce an incomplete, non-functional platform.

---

## Approach

**Approach A — Import Everything, Then Terraform Owns It All**

For every resource that exists in Azure but not in Terraform state: write `import {}` blocks, run `terraform plan` to verify alignment, then `terraform apply` to bring state in sync. Resources with no stable TF provider type (Foundry agents, GitHub secrets) are handled via versioned idempotent bootstrap scripts called by CI before `terraform apply`.

The two genuinely manual steps (CI SP Graph permission, Teams channel portal click) are documented in `BOOTSTRAP.md`.

---

## Section 1: Entra App Registration

### Changes
- Set `enable_entra_apps = true` in `terraform/envs/prod/main.tf`
- Uncomment and complete `import {}` blocks in `imports.tf`:
  - `azuread_application.web_ui` → object ID `8176f860-9715-46e3-8875-5939a6b76a69`
  - `azuread_service_principal.web_ui` → client ID `505df1d3-3bd3-4151-ae87-6e5974b72a44`
- Grant CI SP (`65cf695c-1def-48ba-96af-d968218c90ba`) `Application.ReadWrite.All` on tenant — one-time, documented in `BOOTSTRAP.md`
- Existing `entra-apps` module manages redirect URIs, client ID KV secret — no module changes needed

### Terraform Ownership Going Forward
App registration lifecycle, service principal, redirect URIs, client ID stored in Key Vault.

---

## Section 2: Azure AI Developer Role Assignment (Duplicate Risk)

### Changes
- Import existing manual assignment (`6a001d6b-bc29-4355-962f-0103c81f90c6`) into the state slot `module.rbac.azurerm_role_assignment.agent_rbac["api-gateway-aidev-foundry"]`
- The resource in `modules/rbac/main.tf` is `resource "azurerm_role_assignment" "agent_rbac"` with `for_each = local.role_assignments`
- Import command:
  ```
  terraform import \
    'module.rbac.azurerm_role_assignment.agent_rbac["api-gateway-aidev-foundry"]' \
    /subscriptions/<platform_subscription_id>/providers/Microsoft.Authorization/roleAssignments/6a001d6b-bc29-4355-962f-0103c81f90c6
  ```
- After import, `terraform plan` must show zero changes for this resource

### Terraform Ownership Going Forward
Role assignment fully state-managed; no manual RBAC for this role.

---

## Section 3: Cosmos DB Data-Plane RBAC

### Changes
- Add `azurerm_cosmosdb_sql_role_assignment` resources to `modules/databases/cosmos.tf`
- Built-in role: `Cosmos DB Built-in Data Contributor` (ID `00000000-0000-0000-0000-000000000002`)
- New variable `agent_principal_ids` (map of name → principal_id) passed from root, sourced from container app MI outputs
- Scope: Cosmos account resource ID (`/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.DocumentDB/databaseAccounts/<account>`)
- Import ID format for existing assignments:
  ```
  /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.DocumentDB/databaseAccounts/<account>/sqlRoleAssignments/<guid>
  ```
- Assignments are for the **9 agent container apps + API gateway = 10 principals**. The web-UI container app (`ca-web-ui-prod`) does NOT require Cosmos data-plane access and is excluded. This reconciles with `MANUAL-SETUP.md` Step 4c which lists 10 assignments.
- Add `import {}` blocks for the 10 existing manually-created assignments; any missing ones created fresh on apply

### Terraform Ownership Going Forward
All data-plane RBAC. Adding a new agent automatically grants it Cosmos access via the map.

---

## Section 4: Azure Bot / Teams Registration

### Changes
- New `modules/teams-bot/` module containing **only**:
  - `azurerm_bot_service_azure_bot` — the Azure Bot resource (app type: `SingleTenant`; requires `microsoft_app_id`, `microsoft_app_type`, `microsoft_app_tenant_id`, `sku`)
  - `azuread_application` + `azuread_service_principal` for bot Microsoft App ID (separate from the web-UI app reg)
  - `azurerm_key_vault_secret` for `BOT_ID` and `BOT_PASSWORD`
- The `azurerm_container_app.teams_bot` resource **stays in `agent-apps`** — it is not moved. The new module manages only the Azure Bot service resource and its app registration.
- `agent-apps` module reads `BOT_ID` and `BOT_PASSWORD` from Key Vault secrets (output from the new module) rather than from root variables directly — eliminates plaintext credential passing
- Existing root variables `teams_bot_id`, `teams_bot_password`, `teams_channel_id` are **replaced by outputs from the new module** and wired into `agent-apps`
- New root variable: `enable_teams_bot` (bool, default `false`) gates the entire new module; until `true`, agent-apps continues to use the existing placeholder pattern
- Messaging endpoint wired as `https://<teams-bot-CA-fqdn>/api/messages` sourced from existing container app FQDN output
- **Bot app type:** `SingleTenant` — consistent with the single-tenant Entra setup. If the Azure Portal bot was manually created as `MultiTenant`, an import block must reconcile the app type or the bot resource must be recreated.

### Terraform Ownership Going Forward
Bot app registration, bot service resource, credentials in KV, env var injection into container app via KV references.

### Remaining Manual Step
Teams channel enablement in Azure Bot portal — documented in `BOOTSTRAP.md`.

---

## Section 5: Missing tfvars & Environment Variable Wiring

### `terraform.tfvars` additions
| Variable | Value | Why |
|---|---|---|
| `cors_allowed_origins` | `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` | Locks CORS to specific origin instead of `*` |
| `all_subscription_ids` | `["<platform_subscription_id>"]` | Unlocks storage/security/SRE/patch ARM role assignments that currently collapse to zero; also enables `module.activity_log` to create one `azurerm_monitor_diagnostic_setting` (new resource, no import needed) |

**Note:** `log_analytics_workspace_customer_id` is already wired in `prod/main.tf` via `module.monitoring` output — no change needed.

### `agent-apps` module additions
- `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` added as explicit env vars on all container apps
- Sourced from existing root variable `var.client_id` (the CI SP client ID, `65cf695c-...`) and existing `var.tenant_id`
- No new root variable needed — `var.client_id` already declared in `envs/prod/variables.tf`
- Eliminates the class of "env vars set manually then wiped on next apply"

### `credentials.tfvars` additions (sensitive, gitignored)
| Variable | Where Declared | Purpose |
|---|---|---|
| `postgres_dsn` | Must be added to `envs/prod/variables.tf` AND passed to `module.agent_apps` in `prod/main.tf` | Wired to EOL agent's `POSTGRES_DSN` env var |
| `fabric_admin_email` | Already declared in root variables | Required for `module.fabric` apply even with data plane disabled |

---

## Section 6: PostgreSQL & GitHub Secrets

### pgvector Extension
- The `CREATE EXTENSION IF NOT EXISTS vector;` SQL command is **not added as a `null_resource` / `local-exec`** in Terraform — this approach was explicitly rejected in `modules/databases/postgres.tf` (comment `ISSUE-04`) because the PostgreSQL server is VNet-injected with `public_network_access_enabled = false` and GitHub-hosted runners cannot reach it directly.
- The existing solution — opening a temp firewall rule in the `terraform-apply.yml` CI workflow (PLAN-05 task 05.04) — is already correct and remains in place. No Terraform change needed here.
- **Action:** Verify the CI workflow step exists and has been run successfully in prod. If not, trigger it manually from CI.

### PostgreSQL Entra Auth Administrator
- The server already has `active_directory_auth_enabled = true` in `modules/databases/postgres.tf`
- The missing piece is `azurerm_postgresql_flexible_server_active_directory_administrator` for the API gateway MI
- This resource is added to `modules/databases/postgres.tf` gated on `enable_postgres_entra_auth` bool (default `true` — consistent with the server already having Entra auth enabled)
- Non-breaking: existing password-auth connections continue to work until agents are migrated

### GitHub Actions Secrets
- Add `scripts/bootstrap-github-secrets.sh` wrapping `gh secret set` for:
  - `POSTGRES_ADMIN_PASSWORD`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_KEY`
- Reads values from environment variables (never hardcoded); idempotent
- Documented in `BOOTSTRAP.md`

---

## Section 7: Foundry Agents Bootstrap Script

### Changes
- Extend `scripts/provision-foundry-agents.py`:
  - Creates all 9 agents (orchestrator + 8 domain) idempotently — checks by name before creating
  - Uses `azure-ai-projects` SDK
  - Outputs `agents.tfvars` with all agent IDs in correct variable format
  - `agents.tfvars` is gitignored — generated fresh each bootstrap run
- Update `.github/workflows/terraform-apply.yml`:
  - Run `provision-foundry-agents.py` as a pre-apply step
  - Pass generated `agents.tfvars` via `-var-file` flag to `terraform apply`

### Why Not Terraform
No stable TF resource type exists for Foundry assistant objects (`Microsoft.Foundry/agents` is in `2025-10-01-preview` and subject to breaking changes). The bootstrap script pattern mirrors how `orchestrator_agent_id` is already managed.

---

## BOOTSTRAP.md — Documented Manual Steps

Two steps that have no automation path:

1. **Grant CI SP `Application.ReadWrite.All`** on the Entra tenant — one-time, must be done **before** Step 2 of the implementation sequence (Entra import). Required for `azuread` provider to manage app registrations.
2. **Enable Teams channel** in Azure Bot portal after `enable_teams_bot = true` apply — no stable TF resource for channel configuration

## Intentionally Out-of-Scope Items

- **`enable_fabric_data_plane = false`** — deliberately disabled in `prod/main.tf`. Fabric workspace, Eventhouse, Activator, and Lakehouse are deferred to a future milestone. This is not drift — it is a conscious phase gate.
- **`MANUAL-SETUP.md`** — will be updated to remove steps that are automated by this work and forward-reference `BOOTSTRAP.md` for the two remaining manual steps. This is an explicit deliverable in the implementation sequence.

---

## Implementation Sequence

The changes must be applied in this order to avoid plan failures:

0. **(Manual prerequisite)** Grant CI SP `Application.ReadWrite.All` on the Entra tenant — required before Step 2
1. **Import Azure AI Developer role assignment** — eliminates duplicate risk before any further applies
2. **Import Entra app registration** — set `enable_entra_apps = true`, complete import blocks in `imports.tf`, apply
3. **Add Cosmos data-plane RBAC** — add `azurerm_cosmosdb_sql_role_assignment` resources + import blocks, apply
4. **Add teams-bot module** — add module with `enable_teams_bot = false`; plan/apply to verify zero changes; then set `enable_teams_bot = true` and apply to create bot resource
5. **Fix tfvars & env var wiring** — `cors_allowed_origins`, `all_subscription_ids`, `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`; declare `postgres_dsn` in `prod/variables.tf` and wire to `module.agent_apps`; apply (activity log diagnostic setting will be created as a new resource — expected)
6. **Add PostgreSQL Entra auth administrator** — add `azurerm_postgresql_flexible_server_active_directory_administrator`, apply
7. **Extend Foundry agents script** — update `provision-foundry-agents.py` to be idempotent and output `agents.tfvars`; update CI workflow to run it pre-apply
8. **Update `MANUAL-SETUP.md`** — remove steps now automated; add forward reference to `BOOTSTRAP.md`; write `BOOTSTRAP.md` with the two remaining manual steps
9. **Add `scripts/bootstrap-github-secrets.sh`** — wire missing CI secrets
10. **Final `terraform plan`** — must show zero unexpected changes

---

## Success Criteria

- `terraform apply` from a clean state produces a fully functional platform (excluding the two documented manual steps in `BOOTSTRAP.md`)
- `terraform plan` on the existing prod state shows zero unintended changes after all imports
- `terraform state list | grep cosmosdb_sql_role_assignment` shows 10 entries (one per agent MI + API gateway)
- `terraform state list | grep azuread_application` shows the web-UI app registration
- `terraform state list | grep bot_service` shows the Azure Bot resource (after `enable_teams_bot = true`)
- No more resources in Azure that are invisible to `terraform state list`
- CI pipeline runs `provision-foundry-agents.py` before `terraform apply` automatically and passes `agents.tfvars`
- `BOOTSTRAP.md` documents everything a new operator needs beyond `terraform apply`
- `MANUAL-SETUP.md` is updated to remove automated steps and references `BOOTSTRAP.md`
