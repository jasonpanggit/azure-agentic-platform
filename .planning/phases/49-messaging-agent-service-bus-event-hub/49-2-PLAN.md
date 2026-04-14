---
wave: 2
depends_on: [49-1-PLAN.md]
files_modified:
  - terraform/modules/agent-apps/main.tf
  - terraform/modules/agent-apps/variables.tf
  - terraform/envs/prod/main.tf
  - terraform/envs/prod/terraform.tfvars
  - .github/workflows/agent-images.yml
autonomous: true
---

# Plan 49-2: Messaging Agent — Terraform + CI/CD

## Goal

Wire the `messaging` domain agent into infrastructure: add `messaging` to the Terraform `locals.agents` map (so `ca-messaging-prod` Container App is provisioned), add A2A connection variables, add `MESSAGING_AGENT_ID` env var injection, extend the prod environment tfvars with placeholder variables, and add `build-messaging` + `deploy-messaging` CI/CD jobs to `agent-images.yml`.

## Context

All Terraform patterns for domain agents are established. The `locals.agents` for_each map drives Container App provisioning — adding `messaging` creates `ca-messaging-prod` automatically. The `a2a_domains_all` local registers the agent as an A2A connection in Foundry. Agent ID injection uses the same `dynamic "env"` block pattern as all other domain agents. The CI workflow (`agent-images.yml`) adds one `build-*` + one `deploy-*` job pair following the `build-eol` / `deploy-eol` pattern exactly.

<threat_model>
## Security Threat Assessment

**1. New Container App `ca-messaging-prod`**: Uses `identity { type = "SystemAssigned" }` — managed identity is auto-created. No service principal secrets. RBAC (Reader + Monitoring Reader) provisioned via the `rbac` module in Plan 49-2 Task 4.

**2. `MESSAGING_AGENT_ID` env var injection**: Follows same `dynamic "env"` pattern as all other domain agents — only injected on `orchestrator` and `api-gateway` containers when the var is non-empty. Foundry agent IDs (`asst_xxx`) are not secrets (they are identifiers, not credentials).

**3. `messaging_agent_endpoint` variable**: Empty string default — A2A connection resource is skipped when empty (gated by `for k, v in local.a2a_domains_all : k => v if v != ""`). No resource created without a valid endpoint.

**4. CI/CD build job**: Reuses existing `docker-push.yml` reusable workflow with same secrets. No new secret exposure — same `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` as all other agents.

**5. `use_placeholder_image` guard**: Initial deploy uses placeholder until ACR image is built — same as all other agents. Prevents Container App from pulling a non-existent image tag.

**6. Terraform `terraform.tfvars` placeholder variables**: `messaging_agent_id = ""` and `messaging_agent_endpoint = ""` are empty defaults — the agent will not be injected until an operator populates these after provisioning the Foundry agent. This is the correct launch sequence.

**7. Image path in CI**: `image_name: agents/messaging` → ACR path `agents/messaging`. Follows the same naming pattern as all other agents. No collision risk.
</threat_model>

---

## Tasks

### Task 1: Update `terraform/modules/agent-apps/main.tf` — add `messaging` to `locals.agents` and `a2a_domains_all`

<read_first>
- `terraform/modules/agent-apps/main.tf` — FULL FILE (lines 1–553 as read) — current `locals.agents` map (lines 1–12), `a2a_domains_all` local (lines 518–527), `dynamic "env"` blocks for domain agent IDs (lines 150–205), for_each image path logic (line 51)
- `terraform/modules/agent-apps/variables.tf` — `a2a_domains_all` variable patterns for `compute_agent_endpoint`, `storage_agent_endpoint` etc. to confirm `messaging_agent_endpoint` naming
</read_first>

<action>
Make 3 changes to `terraform/modules/agent-apps/main.tf`:

**Change 1 — `locals.agents` map (around line 11):** Add `messaging` entry after `eol`:
```hcl
    messaging    = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
```

The updated `locals.agents` block:
```hcl
locals {
  agents = {
    orchestrator = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    compute      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    network      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    storage      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    security     = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    arc          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    sre          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    patch        = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    eol          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    messaging    = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
  }
  ...
}
```

**Change 2 — `a2a_domains_all` local (around line 518):** Add `messaging` entry:
```hcl
  a2a_domains_all = {
    compute   = var.compute_agent_endpoint
    arc       = var.arc_agent_endpoint
    eol       = var.eol_agent_endpoint
    network   = var.network_agent_endpoint
    patch     = var.patch_agent_endpoint
    security  = var.security_agent_endpoint
    sre       = var.sre_agent_endpoint
    storage   = var.storage_agent_endpoint
    messaging = var.messaging_agent_endpoint
  }
```

**Change 3 — `MESSAGING_AGENT_ID` dynamic env block:** Add after the `EOL_AGENT_ID` dynamic env block (after line ~205). Insert:
```hcl
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.messaging_agent_id != "" ? [1] : []
        content {
          name  = "MESSAGING_AGENT_ID"
          value = var.messaging_agent_id
        }
      }
```
</action>

<acceptance_criteria>
- `grep "messaging" terraform/modules/agent-apps/main.tf` — exits 0 and returns at least 3 lines
- `grep 'messaging.*cpu.*0.5' terraform/modules/agent-apps/main.tf` exits 0 (new agents entry)
- `grep 'messaging = var.messaging_agent_endpoint' terraform/modules/agent-apps/main.tf` exits 0 (a2a map entry)
- `grep 'MESSAGING_AGENT_ID' terraform/modules/agent-apps/main.tf` exits 0 (dynamic env block)
- `terraform fmt -check terraform/modules/agent-apps/main.tf` exits 0
</acceptance_criteria>

---

### Task 2: Update `terraform/modules/agent-apps/variables.tf` — add `messaging_agent_id` and `messaging_agent_endpoint`

<read_first>
- `terraform/modules/agent-apps/variables.tf` — FULL FILE — current last variable block (`log_analytics_workspace_resource_id` at line ~310) and the A2A endpoint variable pattern for `eol_agent_endpoint` (lines 245–249)
</read_first>

<action>
Add 2 new variable declarations to `terraform/modules/agent-apps/variables.tf` after the `log_analytics_workspace_resource_id` variable block (after line ~315):

```hcl
# ---------------------------------------------------------------------------
# Phase 49: Messaging Agent — Foundry agent ID and A2A endpoint
# ---------------------------------------------------------------------------

variable "messaging_agent_id" {
  description = "Foundry Agent ID for the Messaging domain agent (Service Bus + Event Hub)"
  type        = string
  default     = ""
}

variable "messaging_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Messaging agent Container App (A2A)"
  type        = string
  default     = ""
}
```
</action>

<acceptance_criteria>
- `grep 'variable "messaging_agent_id"' terraform/modules/agent-apps/variables.tf` exits 0
- `grep 'variable "messaging_agent_endpoint"' terraform/modules/agent-apps/variables.tf` exits 0
- `grep 'Foundry Agent ID for the Messaging domain agent' terraform/modules/agent-apps/variables.tf` exits 0
- `grep 'Phase 49' terraform/modules/agent-apps/variables.tf` exits 0
- `terraform fmt -check terraform/modules/agent-apps/variables.tf` exits 0
</acceptance_criteria>

---

### Task 3: Update `terraform/envs/prod/main.tf` — pass messaging vars to module

<read_first>
- `terraform/envs/prod/main.tf` — the `module "agent_apps"` block (lines ~241–301) — current agent_id and endpoint variable pass-throughs (lines 261–271)
</read_first>

<action>
In the `module "agent_apps"` block in `terraform/envs/prod/main.tf`, add two new variable pass-throughs after `eol_agent_id = var.eol_agent_id` (around line 271):

```hcl
  messaging_agent_id       = var.messaging_agent_id
  messaging_agent_endpoint = var.messaging_agent_endpoint
```

Also add corresponding variable declarations to `terraform/envs/prod/main.tf`'s variable block — check if a `var.messaging_agent_id` already has a declaration in the file, and add if not. The prod environment uses `terraform.tfvars` for values, but variables still need declarations. Add:
```hcl
variable "messaging_agent_id" {
  description = "Foundry Agent ID for the Messaging domain agent"
  type        = string
  default     = ""
}

variable "messaging_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Messaging agent Container App (A2A)"
  type        = string
  default     = ""
}
```

Note: Check if the prod env uses a separate `variables.tf` or declares variables inline in `main.tf`. Read `terraform/envs/prod/main.tf` carefully — if variables are declared in a separate `variables.tf` in that directory, add there instead.
</action>

<acceptance_criteria>
- `grep 'messaging_agent_id' terraform/envs/prod/main.tf` exits 0 (module call pass-through)
- `grep 'messaging_agent_endpoint' terraform/envs/prod/main.tf` exits 0
- `terraform fmt -check terraform/envs/prod/main.tf` exits 0 (or the relevant file)
</acceptance_criteria>

---

### Task 4: Update `terraform/envs/prod/terraform.tfvars` — add placeholder variables

<read_first>
- `terraform/envs/prod/terraform.tfvars` — FULL FILE — current structure and the existing `eol_agent_id` / `patch_agent_id` placeholder pattern to mirror
</read_first>

<action>
Add 2 placeholder variable lines to `terraform/envs/prod/terraform.tfvars` after the `eol_agent_id` line (or wherever domain agent IDs are grouped):

```hcl
# Phase 49: Messaging Agent — set after provisioning Foundry agent
messaging_agent_id       = ""
messaging_agent_endpoint = ""
```
</action>

<acceptance_criteria>
- `grep 'messaging_agent_id' terraform/envs/prod/terraform.tfvars` exits 0
- `grep 'messaging_agent_endpoint' terraform/envs/prod/terraform.tfvars` exits 0
- `grep 'Phase 49' terraform/envs/prod/terraform.tfvars` exits 0
- File is valid HCL (no syntax errors — verify by reading it and checking structure)
</acceptance_criteria>

---

### Task 5: Update `.github/workflows/agent-images.yml` — add `messaging` to detect-changes outputs, build and deploy jobs

<read_first>
- `.github/workflows/agent-images.yml` — FULL FILE — all 518 lines; current structure: `detect-changes` job with `outputs` and `filters` blocks, `resolve` step array, `resolve-base-image` condition, `build-eol` job (lines 469–485), `deploy-eol` job (lines 503–517)
</read_first>

<action>
Make 5 targeted changes to `.github/workflows/agent-images.yml`:

**Change 1 — `workflow_dispatch` agent choices (line ~10):** Add `messaging` to the `options` list after `eol`:
```yaml
          - messaging
```

**Change 2 — `on.push.paths` (line ~25):** Add `agents/messaging/**` after `agents/eol/**`:
```yaml
      - 'agents/messaging/**'
```

**Change 3 — `detect-changes` job `outputs` block (~line 55):** Add `messaging` output after `eol`:
```yaml
      messaging: ${{ steps.resolve.outputs.messaging }}
```

**Change 4 — `detect-changes` filters block (~line 88):** Add `messaging` filter after `eol`:
```yaml
            messaging:
              - 'agents/messaging/**'
```

**Change 5 — `detect-changes` resolve step `agents` array and `case` block (~line 95):**
- Add `messaging` to the `agents` array after `eol`: `agents=(orchestrator compute network storage security sre arc patch eol messaging)`
- Add case entry in the `case "$a" in` block after `eol)`:
  ```bash
              messaging)    val="${{ steps.changes.outputs.messaging }}" ;;
  ```

**Change 6 — `resolve-base-image` condition (~line 130):** Add messaging to the `if` condition after `eol`:
```yaml
      needs.detect-changes.outputs.messaging == 'true')
```

**Change 7 — Add `build-messaging` job:** Add after `build-eol` (after line 485):
```yaml
  build-messaging:
    name: Build Messaging Agent
    needs: [detect-changes, resolve-base-image]
    if: needs.detect-changes.outputs.base_related != 'true' && needs.detect-changes.outputs.messaging == 'true'
    uses: ./.github/workflows/docker-push.yml
    with:
      image_name: agents/messaging
      dockerfile_path: agents/messaging/Dockerfile
      build_context: agents/messaging/
      push_image: true
      build_args: |
        BASE_IMAGE=${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ needs.resolve-base-image.outputs.tag }}
    secrets:
      AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
      AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

**Change 8 — Add `deploy-messaging` job:** Add after `deploy-eol` (after line 517):
```yaml
  deploy-messaging:
    needs: [detect-changes, build-messaging]
    if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main' && needs.detect-changes.outputs.base_related != 'true' && needs.detect-changes.outputs.messaging == 'true'
    uses: ./.github/workflows/container-app-deploy.yml
    with:
      image_name: agents/messaging
      image_tag: ${{ github.sha }}
      container_app_name: ca-messaging-prod
      resource_group: ${{ vars.AZURE_RESOURCE_GROUP }}
      github_environment: production
    secrets:
      AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
      AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```
</action>

<acceptance_criteria>
- `grep "messaging" .github/workflows/agent-images.yml` — returns at least 8 lines
- `grep "build-messaging:" .github/workflows/agent-images.yml` exits 0
- `grep "deploy-messaging:" .github/workflows/agent-images.yml` exits 0
- `grep "agents/messaging/\*\*" .github/workflows/agent-images.yml` exits 0 (paths filter)
- `grep "ca-messaging-prod" .github/workflows/agent-images.yml` exits 0 (deploy job)
- `grep "agents/messaging" .github/workflows/agent-images.yml | grep "image_name"` exits 0
- YAML is valid — file parses without error (check by reading it and verifying indentation)
</acceptance_criteria>

---

## Verification

After all tasks complete, verify Terraform formatting passes across all modified modules:

```bash
terraform fmt -check terraform/modules/agent-apps/
terraform fmt -check terraform/envs/prod/
```

Both should exit 0.

Verify the CI workflow is valid YAML:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/agent-images.yml'))" && echo "YAML OK"
```

Spot-check that `ca-messaging-prod` will be created by Terraform:
- `grep "messaging" terraform/modules/agent-apps/main.tf` — should show 3+ hits (agents map, a2a map, env block)

## must_haves

- [ ] `terraform/modules/agent-apps/main.tf` `locals.agents` contains `messaging = { cpu = 0.5, ... }`
- [ ] `terraform/modules/agent-apps/main.tf` `a2a_domains_all` contains `messaging = var.messaging_agent_endpoint`
- [ ] `terraform/modules/agent-apps/main.tf` contains dynamic `MESSAGING_AGENT_ID` env block scoped to `["orchestrator", "api-gateway"]`
- [ ] `terraform/modules/agent-apps/variables.tf` declares `messaging_agent_id` and `messaging_agent_endpoint` with `default = ""`
- [ ] `terraform/envs/prod/terraform.tfvars` contains `messaging_agent_id = ""` and `messaging_agent_endpoint = ""`
- [ ] `.github/workflows/agent-images.yml` contains `build-messaging` job using `agents/messaging/Dockerfile`
- [ ] `.github/workflows/agent-images.yml` contains `deploy-messaging` job targeting `ca-messaging-prod`
- [ ] `terraform fmt -check terraform/modules/agent-apps/` exits 0
- [ ] YAML parse check on `agent-images.yml` exits 0
