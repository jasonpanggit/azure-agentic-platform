---
plan: 07-04
title: "Terraform Prod + Security Review"
status: complete
completed: 2026-03-27
---

# Summary: Plan 07-04 — Terraform Prod + Security Review

## Goal

Extend the `agent-apps` Terraform module to support `teams-bot` and `web-ui` Container Apps with
configurable `target_port`, tighten CORS security via an environment variable, introduce a
three-job security CI workflow (bandit + npm audit + secrets scan), and verify the prod
Terraform environment is complete with all 12 modules.

## Tasks Completed

| # | Task | Status |
|---|------|--------|
| 7-04-01 | Make `agent-apps` `target_port` configurable; add `web-ui` (3000) and `teams-bot` (3978) | ✅ Done |
| 7-04-02 | Add `CORS_ALLOWED_ORIGINS` env var support to `services/api-gateway/main.py` | ✅ Done |
| 7-04-03 | Add `cors_allowed_origins` variable to Terraform `agent-apps` module and prod env | ✅ Done |
| 7-04-04 | Create `.github/workflows/security-review.yml` (bandit + npm audit + secrets scan) | ✅ Done |
| 7-04-05 | Verify prod Terraform config is complete — all 12 modules present, no syntax errors | ✅ Done |

## Files Modified

| File | Change |
|------|--------|
| `terraform/modules/agent-apps/main.tf` | Replaced `api_gateway` local with `services` block; added `web-ui` (port 3000) and `teams-bot` (port 3978); changed `image` path to use `agents/` or `services/` prefix; changed `target_port` from hardcoded `8000` to `each.value.target_port`; added `CORS_ALLOWED_ORIGINS` env block |
| `terraform/modules/agent-apps/variables.tf` | Added `variable "cors_allowed_origins"` (default `*`) |
| `terraform/envs/prod/main.tf` | Added `cors_allowed_origins = var.cors_allowed_origins` to `module "agent_apps"` |
| `terraform/envs/prod/variables.tf` | Added `variable "cors_allowed_origins"` (default `*`) |
| `services/api-gateway/main.py` | Replaced hardcoded `allow_origins=["*"]` with `CORS_ALLOWED_ORIGINS` env var; added module-level `_cors_origins` list |
| `.github/workflows/security-review.yml` | **New file** — 3-job CI workflow: Python security (bandit), TypeScript security (npm audit), secrets scan |

## Acceptance Criteria Results

### Task 7-04-01
- [x] `local.services` contains `web-ui` with `target_port = 3000`
- [x] `local.services` contains `teams-bot` with `target_port = 3978`
- [x] `local.services` contains `api-gateway` with `target_port = 8000`
- [x] All agent entries have `target_port = 8000`
- [x] `dynamic "ingress"` block uses `each.value.target_port` (not hardcoded 8000)
- [x] Container image uses `agents/` or `services/` prefix based on `contains(keys(local.agents), each.key)`
- [x] `terraform fmt -check` passes

### Task 7-04-02
- [x] `main.py` contains `CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*")`
- [x] CORS `allow_origins` is set from `_cors_origins` (env var driven)
- [x] Default: `*` when env var not set
- [x] When set (e.g., prod URL), only that origin is allowed

### Task 7-04-03
- [x] `terraform/modules/agent-apps/variables.tf` contains `variable "cors_allowed_origins"`
- [x] `terraform/modules/agent-apps/main.tf` container block has `env { name = "CORS_ALLOWED_ORIGINS" }`
- [x] `terraform/envs/prod/variables.tf` contains `variable "cors_allowed_origins"`
- [x] `terraform/envs/prod/main.tf` `module "agent_apps"` includes `cors_allowed_origins = var.cors_allowed_origins`

### Task 7-04-04
- [x] `.github/workflows/security-review.yml` exists
- [x] Contains 3 jobs: `python-security`, `typescript-security`, `secrets-scan`
- [x] `python-security` runs `bandit -r` on `services/api-gateway/`, `services/arc-mcp-server/`, `services/detection-plane/`, `agents/`
- [x] `typescript-security` runs `npm audit --audit-level=high` on `services/web-ui` and `services/teams-bot`
- [x] `secrets-scan` greps for hardcoded secrets in Python and TypeScript files
- [x] Workflow triggers on push to `main` and PRs touching `services/**`

### Task 7-04-05
- [x] `terraform/envs/prod/main.tf` contains `module "agent_apps"` with `cors_allowed_origins`
- [x] All 12 modules present: monitoring, networking, foundry, databases, compute_env, keyvault, private_endpoints, agent_apps, rbac, eventhub, fabric, activity_log
- [x] `terraform fmt -check` passes on both module and prod env

## Verification

```
terraform fmt -check terraform/modules/agent-apps/main.tf  → PASS
terraform fmt -check terraform/envs/prod/main.tf           → PASS
```

- `local.services` block confirmed in `agent-apps/main.tf` with correct ports
- `ingress.target_port` now reads from `each.value.target_port`
- Image path interpolation uses ternary: `agents/` vs `services/`
- `CORS_ALLOWED_ORIGINS` env var wired end-to-end: Python → Terraform variable → Container App env
- Security CI workflow covers all 3 vectors (SAST, dependency audit, secrets grep)

## Commit

See git log for commit hash.
