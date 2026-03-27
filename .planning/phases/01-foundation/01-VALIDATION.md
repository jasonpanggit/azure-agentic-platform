---
phase: 1
slug: foundation
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-26
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Terraform CLI (`terraform validate`, `terraform plan`, `terraform fmt`) |
| **Config file** | N/A — no pytest; IaC-only phase |
| **Quick run command** | `cd terraform/modules/<module> && terraform validate` |
| **Full suite command** | `terraform fmt -check -recursive terraform/ && cd terraform/envs/<env> && terraform plan` |
| **Estimated runtime** | ~30 seconds (validate per module), ~2–5 minutes (plan per env) |

---

## Sampling Rate

- **After every task commit:** Run `terraform validate` in the affected module directory
- **After every plan wave:** Run `terraform fmt -check -recursive terraform/` + `terraform plan` for all 3 envs
- **Before `/gsd:verify-work`:** Full plan for dev/staging/prod must be clean
- **Max feedback latency:** 30 seconds (validate), 5 minutes (full plan)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | INFRA-001 | lint | `.gitignore` present; `git status` shows no untracked .tfstate files | ✅ | ✅ green |
| 1-01-02 | 01 | 1 | INFRA-008 | infra | `scripts/bootstrap-state.sh` is executable | ✅ | ✅ green |
| 1-01-03 | 01 | 1 | INFRA-001 | terraform | `cd terraform/modules/monitoring && terraform validate` exits 0 | ✅ | ✅ green |
| 1-01-04 | 01 | 1 | INFRA-001 | terraform | `cd terraform/modules/networking && terraform validate` exits 0 (skeleton) | ✅ | ✅ green |
| 1-01-05 | 01 | 1 | INFRA-002 | terraform | `cd terraform/modules/foundry && terraform validate` exits 0 (skeleton) | ✅ | ✅ green |
| 1-01-06 | 01 | 1 | INFRA-003 | terraform | `cd terraform/modules/databases && terraform validate` exits 0 (skeleton) | ✅ | ✅ green |
| 1-01-07 | 01 | 1 | INFRA-004 | terraform | `cd terraform/modules/compute-env && terraform validate` exits 0 (skeleton) | ✅ | ✅ green |
| 1-01-08 | 01 | 1 | INFRA-001 | terraform | `cd terraform/modules/keyvault && terraform validate` exits 0 (skeleton) | ✅ | ✅ green |
| 1-01-09 | 01 | 1 | INFRA-001 | terraform | `cd terraform/modules/private-endpoints && terraform validate` exits 0 (skeleton) | ✅ | ✅ green |
| 1-02-01 | 02 | 2 | INFRA-001 | terraform | `cd terraform/modules/networking && terraform validate` exits 0 (VNet + subnets) | ✅ | ✅ green |
| 1-02-02 | 02 | 2 | INFRA-001 | terraform | `cd terraform/modules/networking && terraform validate` exits 0 (NSGs) | ✅ | ✅ green |
| 1-02-03 | 02 | 2 | INFRA-001 | terraform | `cd terraform/modules/networking && terraform validate` exits 0 (DNS zones) | ✅ | ✅ green |
| 1-03-01 | 03 | 2 | INFRA-002 | terraform | `cd terraform/modules/foundry && terraform validate` exits 0 (full impl) | ✅ | ✅ green |
| 1-03-02 | 03 | 2 | INFRA-002 | terraform | `cd terraform/modules/foundry && terraform validate` exits 0 (capability host) | ✅ | ✅ green |
| 1-03-03 | 03 | 2 | INFRA-003 | terraform | `cd terraform/modules/databases && terraform validate` exits 0 (Cosmos DB) | ✅ | ✅ green |
| 1-03-04 | 03 | 2 | INFRA-003 | terraform | `cd terraform/modules/databases && terraform validate` exits 0 (PostgreSQL) | ✅ | ✅ green |
| 1-03-05 | 03 | 2 | INFRA-004 | terraform | `cd terraform/modules/compute-env && terraform validate` exits 0 (full impl) | ✅ | ✅ green |
| 1-03-06 | 03 | 2 | INFRA-001 | terraform | `cd terraform/modules/keyvault && terraform validate` exits 0 (full impl) | ✅ | ✅ green |
| 1-03-07 | 03 | 2 | INFRA-001 | terraform | `cd terraform/modules/private-endpoints && terraform validate` exits 0 (full impl) | ✅ | ✅ green |
| 1-04-01 | 04 | 3 | INFRA-008 | terraform | `cd terraform/envs/dev && terraform validate` exits 0 | ✅ | ✅ green |
| 1-04-02 | 04 | 3 | INFRA-008 | terraform | `cd terraform/envs/staging && terraform validate` exits 0 | ✅ | ✅ green |
| 1-04-03 | 04 | 3 | INFRA-008 | terraform | `cd terraform/envs/prod && terraform validate` exits 0 | ✅ | ✅ green |
| 1-05-01 | 05 | 4 | INFRA-008 | yaml | `.github/workflows/terraform-plan.yml` present; YAML syntax valid | ✅ | ✅ green |
| 1-05-02 | 05 | 4 | INFRA-008 | yaml | `.github/workflows/terraform-apply.yml` present; YAML syntax valid | ✅ | ✅ green |
| 1-05-03 | 05 | 4 | INFRA-004 | yaml | `.github/workflows/docker-push.yml` present; YAML syntax valid | ✅ | ✅ green |
| 1-05-04 | 05 | 4 | INFRA-001 | yaml | `terraform-plan.yml` contains `jq` tag lint step that reads `tfplan.json` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Phase 1 is IaC-only — no Wave 0 test infrastructure required. Terraform CLI (`terraform validate`) is the test harness. Module skeleton files (variables.tf, outputs.tf) created in Plan 01-01 served as the "Wave 0 equivalent" that enabled parallel downstream implementation.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `terraform apply` succeeds on real subscription | INFRA-001, INFRA-002, INFRA-003, INFRA-004 | Requires live Azure subscription with OIDC credentials | Run `cd terraform/envs/dev && terraform apply` with real `subscription_id` and `tenant_id`; confirm all resources exist in Azure Portal |
| OIDC auth works in CI (no client secret) | INFRA-008 | Requires GitHub environment secrets and Entra federated credential configured | Push a PR and verify `terraform-plan.yml` workflow authenticates successfully via `azure/login@v2` |
| pgvector extension is active | INFRA-003 | Requires live PostgreSQL Flexible Server reachable via temporary firewall rule | During `terraform-apply.yml` run, confirm `CREATE EXTENSION IF NOT EXISTS vector;` step completes with exit code 0 |
| Tag lint catches untagged resources | INFRA-001 | Requires a real terraform plan JSON with resource definitions | Add a test resource without `managed-by` tag, run `terraform plan -out=tfplan.binary && terraform show -json tfplan.binary > tfplan.json`, then run the jq tag lint command and confirm failure |
| Separate backends have zero state bleed | INFRA-008 | Requires all 3 state storage accounts provisioned (run `bootstrap-state.sh`) | Run `terraform workspace select dev` and `terraform plan` — confirm no prod resources appear |

---

## Validation Sign-Off

- [x] All tasks have terraform validate or yaml lint as automated verify
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 not applicable (IaC-only phase); module skeletons served equivalent function
- [x] No watch-mode flags
- [x] Feedback latency < 30s (validate), < 5m (plan)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** complete
