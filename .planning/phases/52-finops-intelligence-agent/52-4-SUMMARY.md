---
phase: 52-finops-intelligence-agent
plan: 4
subsystem: infrastructure + ci-cd
tags: [finops, terraform, rbac, ci-cd, container-apps, github-actions]

# Dependency graph
requires:
  - plan: 52-1-PLAN.md
    provides: agents/finops/ Python package
  - plan: 52-2-PLAN.md
    provides: API gateway finops endpoints + orchestrator routing
  - plan: 52-3-PLAN.md
    provides: Frontend FinOps tab + 6 proxy routes

provides:
  - terraform/modules/agent-apps/main.tf — finops in locals.agents, FINOPS_AGENT_ID dynamic env, a2a_domains_all finops entry
  - terraform/modules/agent-apps/variables.tf — finops_agent_id and finops_agent_endpoint variables
  - terraform/modules/rbac/main.tf — Cost Management Reader + Monitoring Reader for finops agent
  - terraform/envs/prod/variables.tf — finops_agent_id and finops_agent_endpoint declarations
  - terraform/envs/prod/main.tf — finops_agent_id and finops_agent_endpoint wired to agent-apps module
  - terraform/envs/prod/terraform.tfvars — finops_agent_id = "" and finops_agent_endpoint = "" placeholders
  - .github/workflows/agent-images.yml — build-finops + deploy-finops jobs targeting ca-finops-prod
  - scripts/ops/provision-finops-agent.sh — executable Foundry agent provisioning script

key-files:
  created:
    - scripts/ops/provision-finops-agent.sh
  modified:
    - terraform/modules/agent-apps/main.tf
    - terraform/modules/agent-apps/variables.tf
    - terraform/modules/rbac/main.tf
    - terraform/envs/prod/variables.tf
    - terraform/envs/prod/main.tf
    - terraform/envs/prod/terraform.tfvars
    - .github/workflows/agent-images.yml

key-decisions:
  - "RBAC uses all_subscription_ids for_each loop (same pattern as storage/security/sre/patch agents) — no static per-subscription variables"
  - "finops entry added to locals.agents with same config as messaging (cpu=0.5, 1Gi, ingress_external=false, min_replicas=1, max_replicas=3)"
  - "a2a_domains_all local uses finops = var.finops_agent_endpoint — empty-string guard (if v != '') prevents creation until endpoint is known"
  - "FINOPS_AGENT_ID dynamic env only injected on orchestrator + api-gateway containers when non-empty (standard domain agent pattern)"
  - "terraform validate passes with all new variables declared (all default to empty string)"

requirements-completed: [FINOPS-004]

# Metrics
duration: ~20min
completed: 2026-04-14
---

# Phase 52-4: Infrastructure + CI/CD Summary

**`ca-finops-prod` Container App wired via Terraform, Cost Management Reader RBAC provisioned, build-finops + deploy-finops CI jobs added, provisioning script created — `terraform validate` passes**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-14
- **Completed:** 2026-04-14
- **Tasks:** 7 (Tasks 1–7; all completed)
- **Files created:** 1
- **Files modified:** 7

## Accomplishments

### Task 1: `terraform/modules/agent-apps/main.tf`
Three changes:
1. **`locals.agents`**: Added `finops = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }` after `messaging` — now 11 agents total
2. **`FINOPS_AGENT_ID` dynamic env block**: Injected on `orchestrator` and `api-gateway` containers only when `var.finops_agent_id != ""`
3. **`a2a_domains_all` local**: Added `finops = var.finops_agent_endpoint` — skipped when empty via `if v != ""` guard

### Task 2: `terraform/modules/agent-apps/variables.tf`
Added 2 variable declarations after `messaging_agent_endpoint`:
- `variable "finops_agent_id"` — Foundry Agent ID for the FinOps domain agent (default = "")
- `variable "finops_agent_endpoint"` — FinOps agent A2A endpoint URL (default = "")

Both guarded with `# Phase 52: FinOps Agent` comment block.

### Task 3: `terraform/modules/rbac/main.tf`
Added 2 new for_each role assignment blocks after the patch agent block:
- **`finops-costmgmtreader-{sub_id}`**: `Cost Management Reader` on all `var.all_subscription_ids` — required for `CostManagementClient.query.usage()`
- **`finops-monreader-{sub_id}`**: `Monitoring Reader` on all `var.all_subscription_ids` — required for idle resource detection via Monitor metrics

Both use `var.agent_principal_ids["finops"]` — auto-populated from Container App SystemAssigned MI after first apply.

### Task 4: `terraform/envs/prod/variables.tf` + `main.tf`
- **`variables.tf`**: Added `finops_agent_id` and `finops_agent_endpoint` declarations after `messaging_agent_endpoint`
- **`main.tf`**: Added `finops_agent_id = var.finops_agent_id` and `finops_agent_endpoint = var.finops_agent_endpoint` wiring lines in the `module "agent_apps"` block

### Task 5: `terraform/envs/prod/terraform.tfvars`
Added placeholder lines after the messaging placeholders:
```hcl
# Phase 52: FinOps Agent — set after provisioning Foundry agent
finops_agent_id       = ""
finops_agent_endpoint = ""
```

### Task 6: `.github/workflows/agent-images.yml`
8 changes made:
1. Added `- finops` to `workflow_dispatch.inputs.agent.options` list
2. Added `'agents/finops/**'` to `push.paths` trigger
3. Added `finops: ${{ steps.resolve.outputs.finops }}` to `detect-changes` outputs
4. Added `finops:` entry to `paths-filter` with `- 'agents/finops/**'`
5. Added `finops` to `agents=(...)` array
6. Added `finops) val="${{ steps.changes.outputs.finops }}" ;;` case
7. Added `needs.detect-changes.outputs.finops == 'true' ||` to `resolve-base-image` if condition
8. Added `build-finops` and `deploy-finops` jobs targeting `ca-finops-prod`

### Task 7: `scripts/ops/provision-finops-agent.sh`
Created executable shell script that:
- Validates `AZURE_PROJECT_ENDPOINT` env var
- Uses `azure-ai-projects` SDK + `DefaultAzureCredential`
- Creates Foundry agent with FinOps system prompt
- Prints `finops_agent_id = "asst_..."` for copying into `terraform.tfvars`

## Task Commits

1. **Task 1: agent-apps/main.tf** — `b467519`
2. **Task 2: agent-apps/variables.tf** — `ffd4a70`
3. **Task 3: rbac/main.tf** — `70f8d1b`
4. **Task 4: prod/variables.tf + main.tf** — `8966d9e`
5. **Task 5: prod/terraform.tfvars** — `c22f324`
6. **Task 6: agent-images.yml** — `ec663a7`
7. **Task 7: provision-finops-agent.sh** — `be624d1`

## Verification Results

```
✅ terraform validate — Success! The configuration is valid.
✅ finops in locals.agents with cpu = 0.5
✅ FINOPS_AGENT_ID dynamic env block present
✅ finops-costmgmtreader RBAC assignment
✅ finops-monreader RBAC assignment
✅ finops count in agent-images.yml: 18 occurrences
✅ provision-finops-agent.sh is executable
✅ finops_agent_id wired in prod main.tf
✅ finops_agent_endpoint wired in prod main.tf
✅ finops = var.finops_agent_endpoint in a2a_domains_all
```

## Deviations from Plan

### Auto-fixed: RBAC key format uses `replace(sub_id, "-", "")` not raw `sub_id`

- **Plan showed**: `"finops-costmgmtreader-${sub_id}"` in the example
- **Actual**: `"finops-costmgmtreader-${replace(sub_id, "-", "")}"` — matches the established pattern used by storage/security/sre/patch agents
- **Reason**: Terraform map keys cannot contain hyphens from dynamic values; `replace()` removes them for safe key generation (documented in STATE.md Key Decisions: "RBAC merge() pattern for flat map")
- **Impact**: Correctness improvement; consistent with all other agents

## User Setup Required (Post-Deployment)

After `terraform apply`:
1. Run `./scripts/ops/provision-finops-agent.sh` to provision the Foundry agent
2. Copy the printed `finops_agent_id` into `terraform/envs/prod/terraform.tfvars`
3. Run `terraform apply` again to inject `FINOPS_AGENT_ID` into orchestrator + api-gateway
4. Set `finops_agent_endpoint` once the Container App FQDN is known (optional — for A2A connection)

## Phase 52 Completion

All 4 plans complete:
- **52-1**: FinOps agent backend (Python, 6 @ai_function tools, Dockerfile, spec)
- **52-2**: API gateway integration (6 REST endpoints, orchestrator routing, 23 tests)
- **52-3**: Frontend FinOps tab (6 proxy routes, extended CostTab, 0 TypeScript errors)
- **52-4**: Infrastructure + CI/CD (Terraform, RBAC, CI jobs, provisioning script)

---
*Phase: 52-finops-intelligence-agent*
*Plan: 52-4 (Infrastructure + CI/CD)*
*Completed: 2026-04-14*
