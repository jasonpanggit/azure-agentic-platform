---
wave: 3
depends_on: [52-2-PLAN.md, 52-3-PLAN.md]
files_modified:
  - terraform/modules/agent-apps/main.tf
  - terraform/modules/agent-apps/variables.tf
  - terraform/modules/rbac/main.tf
  - terraform/modules/rbac/variables.tf
  - terraform/envs/prod/main.tf
  - terraform/envs/prod/variables.tf
  - terraform/envs/prod/terraform.tfvars
  - .github/workflows/agent-images.yml
  - scripts/ops/provision-finops-agent.sh
autonomous: true
---

# Plan 52-4: Infrastructure + CI/CD

## Goal

Add `ca-finops-prod` Container App via Terraform (`finops` entry in `locals.agents` for_each map), provision `Cost Management Reader` RBAC for the finops managed identity, add `FINOPS_AGENT_ID` env var injection pattern to orchestrator and api-gateway, extend prod environment variables, add `build-finops` + `deploy-finops` CI/CD jobs to `agent-images.yml`, and create a `provision-finops-agent.sh` script.

## Context

All Terraform patterns for domain agents are established and well-tested. The `locals.agents` for_each map in `terraform/modules/agent-apps/main.tf` already contains `messaging` (Phase 49) — adding `finops` follows the exact same pattern. The `rbac/main.tf` already has `Cost Management Reader` on the compute agent (Phase 39); the finops agent needs the same role on all subscription IDs. The CI workflow `agent-images.yml` already has `build-messaging` / `deploy-messaging` as the most recent agent pair to mirror. The `provision-finops-agent.sh` script follows `scripts/ops/provision-messaging-agent.sh` (if it exists) or `scripts/ops/provision-domain-agents.py`.

<threat_model>
## Security Threat Assessment

**1. New Container App `ca-finops-prod`**: Uses `identity { type = "SystemAssigned" }` — managed identity provisioned automatically. No service principal secrets. RBAC assigned via the `rbac` module.

**2. `FINOPS_AGENT_ID` env var injection**: Foundry agent IDs (`asst_xxx`) are identifiers, not credentials. Injection follows the exact `dynamic "env"` pattern used by all other domain agents — only injected on `orchestrator` and `api-gateway` containers when non-empty.

**3. `finops_agent_endpoint` variable**: Empty string default — A2A connection resource is skipped when empty (gated by `for k, v in local.a2a_domains_all : k => v if v != ""`). No resource created without a valid endpoint.

**4. `Cost Management Reader` RBAC scope**: Read-only access to subscription cost data. Does NOT grant compute resource mutation rights. Least-privilege principle maintained.

**5. CI build job**: Reuses existing `.github/workflows/docker-push.yml` reusable workflow with the same secrets (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`). No new secret exposure.

**6. `provision-finops-agent.sh` script**: Does not contain hardcoded secrets — uses `az` CLI auth and environment variables for Foundry project endpoint. Stores output (agent ID) to stdout for operator to copy to `terraform.tfvars`.

**7. `terraform.tfvars` placeholder variables**: `finops_agent_id = ""` and `finops_agent_endpoint = ""` are empty defaults. The agent will NOT be injected into containers until an operator provisions the Foundry agent and populates these values. This is the correct launch sequence used by all other domain agents.
</threat_model>

---

## Tasks

### Task 1: Update `terraform/modules/agent-apps/main.tf` — add `finops` to `locals.agents` and A2A domains

<read_first>
- `terraform/modules/agent-apps/main.tf` — FULL FILE — current `locals.agents` map (lines 1–13: ends with `messaging = {...}`), `a2a_domains_all` local (search for it in file), `dynamic "env"` blocks for domain agent IDs (the `messaging_agent_id` block is the pattern to mirror)
- `terraform/modules/agent-apps/variables.tf` — confirm `messaging_agent_id` and `messaging_agent_endpoint` variable declarations as the pattern to replicate for `finops_agent_id` and `finops_agent_endpoint`
</read_first>

<action>
Make 3 changes to `terraform/modules/agent-apps/main.tf`:

**Change 1 — `locals.agents` map**: Add `finops` entry after `messaging` (around line 12):
```hcl
    finops       = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
```

The updated `locals.agents` block will have 11 agents: `orchestrator`, `compute`, `network`, `storage`, `security`, `arc`, `sre`, `patch`, `eol`, `messaging`, `finops`.

**Change 2 — `dynamic "env"` block for `FINOPS_AGENT_ID`**: Add after the `messaging_agent_id` dynamic env block:
```hcl
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.finops_agent_id != "" ? [1] : []
        content {
          name  = "FINOPS_AGENT_ID"
          value = var.finops_agent_id
        }
      }
```

**Change 3 — `a2a_domains_all` local**: Find the `a2a_domains_all` local block (search for `messaging_agent_endpoint` in it). Add `finops` entry after `messaging`:
```hcl
    finops = var.finops_agent_endpoint
```

The `a2a_domains_all` local is used for Foundry A2A connection creation; empty-string values are skipped via `if v != ""` guard.
</action>

<acceptance_criteria>
- `grep 'finops.*cpu = 0.5' terraform/modules/agent-apps/main.tf` exits 0
- `grep 'FINOPS_AGENT_ID' terraform/modules/agent-apps/main.tf` exits 0
- `grep 'finops_agent_id' terraform/modules/agent-apps/main.tf` exits 0
- `grep 'finops_agent_endpoint' terraform/modules/agent-apps/main.tf` exits 0
- `grep 'finops = var.finops_agent_endpoint' terraform/modules/agent-apps/main.tf` exits 0
</acceptance_criteria>

---

### Task 2: Update `terraform/modules/agent-apps/variables.tf` — add finops agent variables

<read_first>
- `terraform/modules/agent-apps/variables.tf` — last lines — the `messaging_agent_id` and `messaging_agent_endpoint` variable declarations (around lines 317–330) as the exact pattern to replicate
</read_first>

<action>
Add 2 variable declarations to `terraform/modules/agent-apps/variables.tf` after the `messaging_agent_endpoint` variable block:

```hcl
# Phase 52: FinOps Agent — Foundry agent ID and A2A endpoint
# ---------------------------------------------------------------------------

variable "finops_agent_id" {
  description = "Foundry Agent ID for the FinOps domain agent (Cost Management)"
  type        = string
  default     = ""
}

variable "finops_agent_endpoint" {
  description = "FinOps agent A2A endpoint URL (set after provisioning Foundry agent)"
  type        = string
  default     = ""
}
```
</action>

<acceptance_criteria>
- `grep 'variable "finops_agent_id"' terraform/modules/agent-apps/variables.tf` exits 0
- `grep 'variable "finops_agent_endpoint"' terraform/modules/agent-apps/variables.tf` exits 0
- `grep 'Phase 52: FinOps Agent' terraform/modules/agent-apps/variables.tf` exits 0
</acceptance_criteria>

---

### Task 3: Update `terraform/modules/rbac/main.tf` — add `Cost Management Reader` for FinOps agent

<read_first>
- `terraform/modules/rbac/main.tf` lines 37–51 — the existing `compute-costmgmtreader-compute` and `compute-costmgmtreader-platform` role assignments as the exact pattern to replicate
- `terraform/modules/rbac/main.tf` — find the `role_assignments` merge block; add finops entries in a new block after the messaging agent's block (search for `messaging` in the file to find the insertion point)
- `terraform/modules/rbac/variables.tf` — confirm `agent_principal_ids` variable type to ensure `finops` key is accepted
</read_first>

<action>
Add a new role assignment block to the `role_assignments = merge(...)` in `terraform/modules/rbac/main.tf`. Insert after the `messaging` agent block:

```hcl
    # FinOps Agent: Cost Management Reader on all subscription IDs (Phase 52)
    # Required for CostManagementClient.query.usage() and CostManagementClient.budgets.get()
    {
      for sub_id in var.all_subscription_ids :
      "finops-costmgmtreader-${sub_id}" => {
        principal_id         = var.agent_principal_ids["finops"]
        role_definition_name = "Cost Management Reader"
        scope                = "/subscriptions/${sub_id}"
      }
    },

    # FinOps Agent: Monitoring Reader for idle resource detection (Monitor metrics)
    {
      for sub_id in var.all_subscription_ids :
      "finops-monreader-${sub_id}" => {
        principal_id         = var.agent_principal_ids["finops"]
        role_definition_name = "Monitoring Reader"
        scope                = "/subscriptions/${sub_id}"
      }
    },
```

Note: The for loop pattern over `var.all_subscription_ids` is used if the existing rbac module already uses this pattern for messaging or other agents. If the existing pattern uses static subscription variables (`var.compute_subscription_id`), replicate the static pattern using `var.platform_subscription_id` instead.

**Important verification step**: Before writing, read the actual `rbac/main.tf` to confirm whether `all_subscription_ids` for loop is used or individual subscription variables. Use whichever pattern is already present.
</action>

<acceptance_criteria>
- `grep 'finops-costmgmtreader' terraform/modules/rbac/main.tf` exits 0
- `grep 'finops-monreader' terraform/modules/rbac/main.tf` exits 0
- `grep '"Cost Management Reader"' terraform/modules/rbac/main.tf` — returns at least 2 lines (compute + finops)
- `grep 'agent_principal_ids\["finops"\]' terraform/modules/rbac/main.tf` exits 0
</acceptance_criteria>

---

### Task 4: Update `terraform/envs/prod/variables.tf` and `main.tf` — wire finops variables

<read_first>
- `terraform/envs/prod/variables.tf` — search for `messaging_agent_id` and `messaging_agent_endpoint` variable declarations — exact pattern to replicate for finops
- `terraform/envs/prod/main.tf` — search for `messaging_agent_id` and `messaging_agent_endpoint` module wiring lines — exact pattern for finops
</read_first>

<action>
**In `terraform/envs/prod/variables.tf`**: Add 2 variable declarations after `messaging_agent_endpoint`:
```hcl
variable "finops_agent_id" {
  description = "Foundry Agent ID for the FinOps agent"
  type        = string
  default     = ""
}

variable "finops_agent_endpoint" {
  description = "FinOps agent A2A endpoint URL"
  type        = string
  default     = ""
}
```

**In `terraform/envs/prod/main.tf`**: Add 2 variable wiring lines to the `module "agent-apps"` block, after the `messaging_agent_endpoint` line:
```hcl
  finops_agent_id       = var.finops_agent_id
  finops_agent_endpoint = var.finops_agent_endpoint
```

Also add 2 wiring lines to the `module "rbac"` block if `agent_principal_ids` is wired per-agent (check current pattern):
- If `agent_principal_ids` is a map built from module outputs, add `finops = module.agent-apps.agent_principal_ids["finops"]` or equivalent.
</action>

<acceptance_criteria>
- `grep 'variable "finops_agent_id"' terraform/envs/prod/variables.tf` exits 0
- `grep 'variable "finops_agent_endpoint"' terraform/envs/prod/variables.tf` exits 0
- `grep 'finops_agent_id.*=.*var.finops_agent_id' terraform/envs/prod/main.tf` exits 0
- `grep 'finops_agent_endpoint.*=.*var.finops_agent_endpoint' terraform/envs/prod/main.tf` exits 0
</acceptance_criteria>

---

### Task 5: Update `terraform/envs/prod/terraform.tfvars` — add finops placeholder variables

<read_first>
- `terraform/envs/prod/terraform.tfvars` — current content — the `messaging_agent_id = ""` and `messaging_agent_endpoint = ""` placeholder lines (around lines 23–24) as the exact pattern to replicate
</read_first>

<action>
Add 2 placeholder lines to `terraform/envs/prod/terraform.tfvars` after the messaging placeholders:

```hcl
# Phase 52: FinOps Agent — set after provisioning Foundry agent
finops_agent_id       = ""
finops_agent_endpoint = ""
```
</action>

<acceptance_criteria>
- `grep 'finops_agent_id.*=.*""' terraform/envs/prod/terraform.tfvars` exits 0
- `grep 'finops_agent_endpoint.*=.*""' terraform/envs/prod/terraform.tfvars` exits 0
- `grep 'Phase 52: FinOps Agent' terraform/envs/prod/terraform.tfvars` exits 0
</acceptance_criteria>

---

### Task 6: Update `.github/workflows/agent-images.yml` — add `finops` build + deploy jobs

<read_first>
- `.github/workflows/agent-images.yml` — FULL FILE — current `build-messaging` (lines 526–542) and `deploy-messaging` (lines 544–558) jobs as the exact pattern to replicate; the `detect-changes` job outputs (line 59) and `resolve-base-image` if condition (line 146) also need updating
- The `workflow_dispatch.inputs.agent.options` list (lines 10–21) and the `agents=( ... )` array in the resolve step (line 100) must both include `finops`
</read_first>

<action>
Make 6 changes to `.github/workflows/agent-images.yml`:

**Change 1 — `workflow_dispatch` options list** (around line 10): Add `- finops` to the options list after `- messaging`.

**Change 2 — `push.paths` triggers** (around line 38): Add `'agents/finops/**'` after `'agents/messaging/**'`.

**Change 3 — `detect-changes` outputs** (around line 59): Add `finops: ${{ steps.resolve.outputs.finops }}` after `messaging: ${{ steps.resolve.outputs.messaging }}`.

**Change 4 — `detect-changes` paths-filter** (around line 91): Add:
```yaml
            finops:
              - 'agents/finops/**'
```

**Change 5 — Resolve agent flags** (lines 100–123): Add `finops` to the `agents=(...)` array and add the case entry:
```bash
agents=(orchestrator compute network storage security sre arc patch eol messaging finops)
```
and:
```bash
                finops)       val="${{ steps.changes.outputs.finops }}" ;;
```

**Change 6 — `resolve-base-image` if condition** (around line 136): Add:
```yaml
      needs.detect-changes.outputs.finops == 'true' ||
```

**Change 7 — Add `build-finops` job** (after `build-messaging`):
```yaml
  build-finops:
    name: Build FinOps Agent
    needs: [detect-changes, resolve-base-image]
    if: needs.detect-changes.outputs.base_related != 'true' && needs.detect-changes.outputs.finops == 'true'
    uses: ./.github/workflows/docker-push.yml
    with:
      image_name: agents/finops
      dockerfile_path: agents/finops/Dockerfile
      build_context: agents/finops/
      push_image: true
      build_args: |
        BASE_IMAGE=${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ needs.resolve-base-image.outputs.tag }}
    secrets:
      AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
      AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

**Change 8 — Add `deploy-finops` job** (after `deploy-messaging`):
```yaml
  deploy-finops:
    needs: [detect-changes, build-finops]
    if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main' && needs.detect-changes.outputs.base_related != 'true' && needs.detect-changes.outputs.finops == 'true'
    uses: ./.github/workflows/container-app-deploy.yml
    with:
      image_name: agents/finops
      image_tag: ${{ github.sha }}
      container_app_name: ca-finops-prod
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
- `grep '- finops' .github/workflows/agent-images.yml` — returns at least 2 lines (options list + paths or agents array)
- `grep 'agents/finops/\*\*' .github/workflows/agent-images.yml` exits 0
- `grep 'finops.*steps.resolve.outputs.finops' .github/workflows/agent-images.yml` exits 0
- `grep 'build-finops' .github/workflows/agent-images.yml` exits 0
- `grep 'deploy-finops' .github/workflows/agent-images.yml` exits 0
- `grep 'ca-finops-prod' .github/workflows/agent-images.yml` exits 0
- `grep 'image_name: agents/finops' .github/workflows/agent-images.yml` exits 0
</acceptance_criteria>

---

### Task 7: Create `scripts/ops/provision-finops-agent.sh`

<read_first>
- `scripts/ops/` directory — list files to confirm if `provision-messaging-agent.sh` exists as the direct reference; if not, check `provision-domain-agents.py`
- Whichever provisioning script exists for messaging — full content — exact pattern to replicate for finops
</read_first>

<action>
Create `scripts/ops/provision-finops-agent.sh` following the messaging agent provisioning script pattern. If no shell script exists for messaging, create a new minimal script:

```bash
#!/usr/bin/env bash
# provision-finops-agent.sh
#
# Provisions the FinOps Foundry Agent via azure-ai-projects SDK and prints
# the agent ID for insertion into terraform/envs/prod/terraform.tfvars.
#
# Usage:
#   export AZURE_PROJECT_ENDPOINT="https://..."
#   ./scripts/ops/provision-finops-agent.sh
#
# Prerequisites: az login, python3, azure-ai-projects installed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

AZURE_PROJECT_ENDPOINT="${AZURE_PROJECT_ENDPOINT:-}"
if [ -z "$AZURE_PROJECT_ENDPOINT" ]; then
  echo "ERROR: AZURE_PROJECT_ENDPOINT is not set" >&2
  echo "  export AZURE_PROJECT_ENDPOINT=https://<account>.api.azureml.ms/..." >&2
  exit 1
fi

echo "Provisioning FinOps Agent on Foundry project: $AZURE_PROJECT_ENDPOINT"

python3 - <<'PYTHON'
import os
import sys

try:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
except ImportError:
    print("ERROR: azure-ai-projects package not installed. Run: pip install azure-ai-projects>=2.0.1", file=sys.stderr)
    sys.exit(1)

endpoint = os.environ["AZURE_PROJECT_ENDPOINT"]
model = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-4o")

client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())

# Read the system prompt from agent.py (or use a minimal inline prompt)
system_prompt = (
    "You are the AAP FinOps Agent. You reason over Azure Cost Management data to surface "
    "wasteful spend, forecast monthly bills, and propose cost-saving actions through the "
    "existing HITL workflow. Always include data_lag_note in cost responses."
)

agent = client.agents.create_agent(
    model=model,
    name="finops-agent",
    description="FinOps specialist — cost breakdown, idle resource detection, RI utilisation, budget forecasting.",
    instructions=system_prompt,
)

print(f"\nFinOps agent provisioned successfully!")
print(f"  Agent ID: {agent.id}")
print(f"\nAdd to terraform/envs/prod/terraform.tfvars:")
print(f'  finops_agent_id = "{agent.id}"')
PYTHON
```

Make the script executable:
```bash
chmod +x scripts/ops/provision-finops-agent.sh
```
</action>

<acceptance_criteria>
- File `scripts/ops/provision-finops-agent.sh` exists
- `grep "provision-finops-agent" scripts/ops/provision-finops-agent.sh` exits 0
- `grep "AZURE_PROJECT_ENDPOINT" scripts/ops/provision-finops-agent.sh` exits 0
- `grep "finops-agent" scripts/ops/provision-finops-agent.sh` exits 0
- `grep "finops_agent_id" scripts/ops/provision-finops-agent.sh` exits 0
- `grep "terraform.tfvars" scripts/ops/provision-finops-agent.sh` exits 0
- File is executable: `test -x scripts/ops/provision-finops-agent.sh` exits 0
</acceptance_criteria>

---

## Verification

After all tasks complete:

```bash
# 1. Terraform validates without errors
cd terraform/envs/prod && terraform init -backend=false && terraform validate

# 2. finops agent in locals.agents
grep 'finops.*cpu = 0.5' terraform/modules/agent-apps/main.tf

# 3. FINOPS_AGENT_ID injection in main.tf
grep 'FINOPS_AGENT_ID' terraform/modules/agent-apps/main.tf

# 4. RBAC Cost Management Reader for finops
grep 'finops-costmgmtreader' terraform/modules/rbac/main.tf

# 5. CI workflow has finops jobs
grep -c 'finops' .github/workflows/agent-images.yml

# 6. Provisioning script is executable
test -x scripts/ops/provision-finops-agent.sh && echo "OK"
```

Expected: `terraform validate` exits 0, all grep checks find matches, provisioning script is executable.

## must_haves

- [ ] `terraform/modules/agent-apps/main.tf` `locals.agents` contains `finops` entry with `cpu = 0.5, memory = "1Gi", ingress_external = false`
- [ ] `terraform/modules/agent-apps/main.tf` has `FINOPS_AGENT_ID` dynamic env block (injected to orchestrator + api-gateway only when non-empty)
- [ ] `terraform/modules/agent-apps/main.tf` `a2a_domains_all` local contains `finops = var.finops_agent_endpoint`
- [ ] `terraform/modules/agent-apps/variables.tf` declares `finops_agent_id` and `finops_agent_endpoint` variables (default = "")
- [ ] `terraform/modules/rbac/main.tf` has `Cost Management Reader` and `Monitoring Reader` role assignments for `agent_principal_ids["finops"]`
- [ ] `terraform/envs/prod/variables.tf` declares `finops_agent_id` and `finops_agent_endpoint`
- [ ] `terraform/envs/prod/main.tf` wires `finops_agent_id` and `finops_agent_endpoint` to the agent-apps module
- [ ] `terraform/envs/prod/terraform.tfvars` has `finops_agent_id = ""` and `finops_agent_endpoint = ""` placeholder lines
- [ ] `.github/workflows/agent-images.yml` has `build-finops` and `deploy-finops` jobs targeting `ca-finops-prod`
- [ ] `.github/workflows/agent-images.yml` `agents=(...)` array includes `finops`
- [ ] `scripts/ops/provision-finops-agent.sh` is executable and prints `finops_agent_id` for tfvars
- [ ] `terraform validate` passes (exits 0) after all changes
