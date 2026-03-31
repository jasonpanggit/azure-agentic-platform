# TODO — Azure Agentic Platform

Deferred items that are intentionally not done yet. Each entry explains what it is,
why it was deferred, and exactly what to do when ready.

---

## [DEFERRED] Enable Terraform ownership of Entra app registrations

**What:** Set `enable_entra_apps = true` in `terraform/envs/prod/terraform.tfvars` so
Terraform manages the web-UI MSAL app registration (`aap-web-ui-prod`) and the Teams bot
app registration lifecycle (redirect URIs, client ID in Key Vault, secret rotation).

**Why deferred:** Requires a Global Administrator of the `xtech-sg.net` Entra tenant to
admin-consent `Application.ReadWrite.All` for the CI service principal
(`65cf695c-1def-48ba-96af-d968218c90ba`). The app registration already exists and works —
this is about Terraform owning it going forward, not about it being broken today.

**Note:** The permission request has already been added to the CI SP app registration
manifest (`az ad app permission add` was run on 2026-03-31). Only the admin consent
grant is outstanding.

**To complete:**
1. A Global Admin runs:
   ```bash
   az login --tenant abbdca26-d233-4a1e-9d8c-c4eebbc16e50
   az ad app permission admin-consent --id 65cf695c-1def-48ba-96af-d968218c90ba
   ```
   Or via Portal → App registrations → `65cf695c-...` → API permissions → Grant admin consent

2. In `terraform/envs/prod/terraform.tfvars`, set:
   ```hcl
   enable_entra_apps = true
   ```

3. In `terraform/envs/prod/imports.tf`, uncomment the two entra import blocks.

4. Run: `terraform apply -var-file="credentials.tfvars"`

5. Verify: `terraform state list | grep azuread_application`

**Full procedure:** `docs/BOOTSTRAP.md` Step 1

---

## [DEFERRED] Enable Teams Bot module

**What:** Set `enable_teams_bot = true` in `terraform/envs/prod/terraform.tfvars` to
provision the Azure Bot service resource and Teams bot app registration via Terraform.

**Why deferred:** Blocked on the Entra `Application.ReadWrite.All` grant above (the
teams-bot module creates an Entra app registration for the bot's `microsoft_app_id`).
Also requires uncommenting the import blocks in `terraform/modules/teams-bot/main.tf`
for the existing `aap-teams-bot-prod` Azure Bot resource (msaAppId: `d5b074fc-7ca6-4354-8938-046e034d80da`).

**To complete:**
1. Complete the Entra app registration deferral above first
2. Uncomment import blocks in `terraform/modules/teams-bot/main.tf`
3. Set `enable_teams_bot = true` in `terraform/envs/prod/terraform.tfvars`
4. Run: `terraform apply -var-file="credentials.tfvars"`
5. In Azure Portal → Azure Bot → Channels → Teams → Accept ToS → Apply (see `docs/BOOTSTRAP.md` Step 2)

---
