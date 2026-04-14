# Scale ACR Agent Pool from 1 to 3

| Field | Value |
|---|---|
| **Slug** | `scale-acr-agent-pool` |
| **Branch** | `fix/scale-acr-agent-pool` |
| **Scope** | Terraform module change + prod env wiring |
| **Risk** | Low (additive, no destroy) |
| **Estimated time** | 10 min code, CI applies |

## Problem

Single agent pool (`aap-builder-prod`, S1, count=1) bottlenecks `deploy-all-images` workflow. 12+ parallel `az acr build` jobs queue behind 1 agent, wall-clock >40 min, GitHub runner loses connection.

## Solution

Scale `instance_count` from 1 to 3 via a new Terraform variable (keeps the module reusable across envs). Push to branch, let `terraform-plan.yml` run, merge to main for apply.

## Tasks

### 1. Create branch

```bash
git checkout main && git pull && git checkout -b fix/scale-acr-agent-pool
```

### 2. Add variable to compute-env module

**File:** `terraform/modules/compute-env/variables.tf`

Append:

```hcl
variable "acr_agent_pool_instance_count" {
  description = "Number of ACR agent pool instances (S1 tier)"
  type        = number
  default     = 1

  validation {
    condition     = var.acr_agent_pool_instance_count >= 1 && var.acr_agent_pool_instance_count <= 10
    error_message = "Agent pool count must be between 1 and 10."
  }
}
```

### 3. Use variable in resource

**File:** `terraform/modules/compute-env/main.tf` (line 61)

Change:

```diff
-  instance_count          = 1
+  instance_count          = var.acr_agent_pool_instance_count
```

Update comment on line 60:

```diff
-  # S1: 2 vCPU, 3 GiB RAM — sufficient for sequential image builds
+  # S1: 2 vCPU, 3 GiB RAM per agent — pool size set by variable
```

### 4. Pass variable from prod env

**File:** `terraform/envs/prod/main.tf` (inside `module "compute_env"` block, ~line 134)

Add parameter:

```hcl
  acr_agent_pool_instance_count = 3
```

### 5. Commit and push

```bash
git add terraform/modules/compute-env/variables.tf \
        terraform/modules/compute-env/main.tf \
        terraform/envs/prod/main.tf
git commit -m "fix: scale ACR agent pool from 1 to 3 to reduce build queue contention"
git push -u origin fix/scale-acr-agent-pool
```

### 6. Verify terraform plan

- `terraform-plan.yml` triggers on push to non-main branch
- Confirm plan shows: `azurerm_container_registry_agent_pool.main` will be updated in-place (`instance_count: 1 -> 3`)
- No destroy, no replacement

### 7. Merge and apply

- Open PR, review plan output in PR comment
- Merge to `main` — `terraform-apply.yml` runs `terraform apply -auto-approve`
- Verify in portal: ACR > Agent pools > `aap-builder-prod` shows 3 instances

### 8. Validate

- Re-run `deploy-all-images` workflow
- Confirm parallel builds execute on multiple agents (check ACR build logs for different agent IDs)
- Wall-clock should drop from ~40 min to ~15 min

## Rollback

Set `acr_agent_pool_instance_count = 1` in `terraform/envs/prod/main.tf`, commit, merge. Terraform scales down non-destructively.
