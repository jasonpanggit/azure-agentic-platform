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
- Import existing manual assignment (`6a001d6b-bc29-4355-962f-0103c81f90c6`) into the state slot `module.rbac.azurerm_role_assignment.assignments["api-gateway-aidev-foundry"]`
- Import command:
  ```
  terraform import \
    'module.rbac.azurerm_role_assignment.assignments["api-gateway-aidev-foundry"]' \
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
- Scope: Cosmos account resource ID
- Add `import {}` blocks for the 10 existing manually-created assignments; any missing ones created fresh
- 11 total assignments: all agent MIs + API gateway

### Terraform Ownership Going Forward
All data-plane RBAC. Adding a new agent automatically grants it Cosmos access via the map.

---

## Section 4: Azure Bot / Teams Registration

### Changes
- New `modules/teams-bot/` module containing:
  - `azurerm_bot_service_azure_bot` — the Azure Bot resource
  - `azuread_application` + `azuread_service_principal` for bot Microsoft App ID
  - `azurerm_key_vault_secret` for `BOT_ID` and `BOT_PASSWORD`
- Bot app registration client secret stored in Key Vault; `agent-apps` module reads from KV and injects as container app secret
- New root variable: `enable_teams_bot` (bool, default `false`) gates the entire module
- Removes root variables `teams_bot_id`, `teams_bot_password`, `teams_channel_id` — replaced by module outputs
- Messaging endpoint: `https://<teams-bot-CA-fqdn>/api/messages` sourced from existing container app FQDN output

### Terraform Ownership Going Forward
Bot app registration, bot service resource, credentials in KV, env var injection into container app.

### Remaining Manual Step
Teams channel enablement in Azure Bot portal — documented in `BOOTSTRAP.md`.

---

## Section 5: Missing tfvars & Environment Variable Wiring

### `terraform.tfvars` additions
| Variable | Value | Why |
|---|---|---|
| `log_analytics_workspace_customer_id` | from `module.monitoring` output | Prevents web-UI observability wipe on next apply |
| `cors_allowed_origins` | `https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` | Locks CORS to specific origin instead of `*` |
| `all_subscription_ids` | `["<platform_subscription_id>"]` | Unlocks storage/security/SRE/patch ARM role assignments that currently collapse to zero |

### `agent-apps` module additions
- `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` added as explicit env vars on all container apps
- Sourced from `var.ci_client_id` (new) and existing `var.tenant_id`
- Eliminates the class of "env vars set manually then wiped on next apply"

### `credentials.tfvars` additions (sensitive, gitignored)
| Variable | Purpose |
|---|---|
| `postgres_dsn` | Wired to EOL agent's `POSTGRES_DSN` env var |
| `fabric_admin_email` | Required for `module.fabric` apply even with data plane disabled |

---

## Section 6: PostgreSQL & GitHub Secrets

### pgvector Extension
- Add `null_resource` with `local-exec` provisioner in `modules/databases/postgres.tf`
- Runs `CREATE EXTENSION IF NOT EXISTS vector;` via `psql`
- Gated on `run_db_init` bool variable (default `false`) — only fires in CI with temp firewall rule
- Trigger: `{ extension = "vector" }` — idempotent, not `timestamp()`

### PostgreSQL Entra Auth
- Add `azurerm_postgresql_flexible_server_active_directory_administrator` for API gateway MI
- Gated on `enable_postgres_entra_auth` bool (default `false`) — non-breaking for existing password auth

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

1. **Grant CI SP `Application.ReadWrite.All`** on the Entra tenant — one-time, required before `enable_entra_apps = true` apply succeeds
2. **Enable Teams channel** in Azure Bot portal after `enable_teams_bot = true` apply — no stable TF resource for channel configuration

---

## Implementation Sequence

The changes must be applied in this order to avoid plan failures:

1. **Import Azure AI Developer role assignment** — eliminates duplicate risk before any further applies
2. **Import Entra app registration** — requires `Application.ReadWrite.All` grant first
3. **Add Cosmos data-plane RBAC** — add resources + imports, apply
4. **Add teams-bot module** — add module, set `enable_teams_bot = false`, plan/apply to verify zero changes before enabling
5. **Fix tfvars wiring** — `log_analytics_workspace_customer_id`, `cors_allowed_origins`, `all_subscription_ids`, `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`
6. **Add pgvector null_resource + Postgres Entra auth** — gated off by default
7. **Extend Foundry agents script** — update CI workflow
8. **Write BOOTSTRAP.md** — document the two remaining manual steps
9. **Final `terraform plan`** — must show zero unexpected changes

---

## Success Criteria

- `terraform apply` from a clean state produces a fully functional platform (excluding the two documented manual steps)
- `terraform plan` on the existing prod state shows zero unintended changes after all imports
- No more resources in Azure that are invisible to `terraform state list`
- CI pipeline runs `provision-foundry-agents.py` before `terraform apply` automatically
- `BOOTSTRAP.md` documents everything a new operator needs to know beyond `terraform apply`
