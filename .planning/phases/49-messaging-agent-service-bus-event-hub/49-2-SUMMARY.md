# Phase 49-2 Summary: Messaging Agent — Terraform + CI/CD

**Status:** Complete  
**Wave:** 2  
**Completed:** 2026-04-14

## What Was Done

All 5 tasks completed successfully. The messaging domain agent is now fully wired into infrastructure and CI/CD.

### Task 1: `terraform/modules/agent-apps/main.tf`
- Added `messaging` to `locals.agents` for_each map → Terraform will provision `ca-messaging-prod` Container App
- Added `MESSAGING_AGENT_ID` dynamic env block scoped to `["orchestrator", "api-gateway"]`
- Added `messaging = var.messaging_agent_endpoint` to `a2a_domains_all` local → Foundry A2A connection registration

### Task 2: `terraform/modules/agent-apps/variables.tf`
- Added `messaging_agent_id` variable (Phase 49 comment block)
- Added `messaging_agent_endpoint` variable (both with `default = ""`)

### Task 3: `terraform/envs/prod/main.tf`
- Passed `messaging_agent_id` and `messaging_agent_endpoint` through to `module "agent_apps"` call

### Task 4: `terraform/envs/prod/variables.tf` + `terraform.tfvars`
- Added variable declarations in `variables.tf`
- Added placeholder `messaging_agent_id = ""` and `messaging_agent_endpoint = ""` in `terraform.tfvars`

### Task 5: `.github/workflows/agent-images.yml`
- Added `messaging` to `workflow_dispatch` options list
- Added `agents/messaging/**` to `on.push.paths` trigger
- Added `messaging` output to `detect-changes` job
- Added `messaging` filter to dorny/paths-filter block
- Added `messaging` to agents array and `case` block in resolve step
- Added `messaging` to `resolve-base-image` condition
- Added `build-messaging` job (docker-push.yml reusable workflow)
- Added `deploy-messaging` job targeting `ca-messaging-prod`

## Verification

- `terraform fmt -check` passes on all modified modules
- YAML parse check passes (`python3 -c "import yaml; yaml.safe_load(...)"`)
- 37/37 unit tests pass
- All acceptance criteria met for all 5 tasks

## Next Steps

After initial Terraform apply provisions `ca-messaging-prod`:
1. Run `scripts/provision-domain-agents.py` to create Foundry agent
2. Populate `messaging_agent_id` in `terraform.tfvars`
3. Set `messaging_agent_endpoint` to Container App internal FQDN
4. Re-run `terraform apply` to inject agent ID into orchestrator + api-gateway
