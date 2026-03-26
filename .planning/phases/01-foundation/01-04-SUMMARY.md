---
phase: 01-foundation
plan: "04"
subsystem: infra
tags: [terraform, azure, environments, dev, staging, prod, cosmos-db, postgresql, private-endpoints]

# Dependency graph
requires:
  - phase: 01-foundation/01
    provides: scaffold with provider configs and module structure
  - phase: 01-foundation/02
    provides: networking module with VNet, subnets, DNS zones
  - phase: 01-foundation/03
    provides: all resource modules (monitoring, foundry, databases, compute-env, keyvault, private-endpoints)
provides:
  - 3 environment root compositions (dev, staging, prod) composing all shared modules
  - Independent backend configurations per environment
  - Environment-specific resource sizing (Cosmos, PostgreSQL, Foundry capacity)
affects: [01-foundation/05-ci-cd, phase-2-agent-core, phase-7-prod-apply]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Environment composition: envs/{env}/main.tf composes shared modules with env-specific overrides"
    - "Centralized private endpoints: all PEs in module.private_endpoints, instantiated after resource modules"
    - "OIDC auth everywhere: use_oidc = true in both providers and backends"

key-files:
  created:
    - terraform/envs/dev/main.tf
    - terraform/envs/dev/providers.tf
    - terraform/envs/dev/backend.tf
    - terraform/envs/dev/variables.tf
    - terraform/envs/dev/terraform.tfvars
    - terraform/envs/dev/outputs.tf
    - terraform/envs/staging/main.tf
    - terraform/envs/staging/providers.tf
    - terraform/envs/staging/backend.tf
    - terraform/envs/staging/variables.tf
    - terraform/envs/staging/terraform.tfvars
    - terraform/envs/staging/outputs.tf
    - terraform/envs/prod/main.tf
    - terraform/envs/prod/providers.tf
    - terraform/envs/prod/backend.tf
    - terraform/envs/prod/variables.tf
    - terraform/envs/prod/terraform.tfvars
    - terraform/envs/prod/outputs.tf
  modified: []

key-decisions:
  - "Dev/staging use Cosmos Serverless; prod uses Provisioned Autoscale with westus2 secondary"
  - "PostgreSQL tiered SKUs: dev B1ms, staging B2ms, prod GP_Standard_D4s_v3"
  - "All environments share identical provider/output structure; only module parameters differ"

patterns-established:
  - "Environment composition pattern: envs/{env}/ directory with 6 files composing shared modules"
  - "Backend isolation: separate storage accounts per env (staaptfstatedev, staaptfstatestg, staaptfstateprod)"

requirements-completed: [INFRA-001, INFRA-002, INFRA-003, INFRA-004, INFRA-008]

# Metrics
duration: 3min
completed: 2026-03-26
---

# Phase 1 Plan 04: Environment Composition Summary

**Three environment roots (dev/staging/prod) composing all 7 shared Terraform modules with tiered Cosmos DB, PostgreSQL, and Foundry capacity per environment**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-26T03:21:43Z
- **Completed:** 2026-03-26T03:24:55Z
- **Tasks:** 3
- **Files created:** 18

## Accomplishments
- Created dev, staging, and prod environment roots each composing all 7 shared modules (monitoring, networking, foundry, databases, compute-env, keyvault, private-endpoints)
- Established tiered resource sizing: dev (Serverless/B1ms) → staging (Serverless/B2ms) → prod (Provisioned Autoscale/GP_Standard_D4s_v3)
- Independent backend configs with OIDC auth — no shared state between environments
- All 23 outputs per environment covering every module surface for downstream consumption

## Task Commits

Each task was committed atomically:

1. **Task 04.01: Create dev environment root** - `a447027` (feat)
2. **Task 04.02: Create staging environment root** - `1119e07` (feat)
3. **Task 04.03: Create prod environment root** - `5f5c7a8` (feat)

## Files Created/Modified
- `terraform/envs/dev/providers.tf` - Provider requirements: azurerm ~>4.65.0, azapi ~>2.9.0, random ~>3.6
- `terraform/envs/dev/backend.tf` - Remote state backend targeting staaptfstatedev
- `terraform/envs/dev/variables.tf` - Root variables: subscription_id, tenant_id, location, environment, postgres_admin_password
- `terraform/envs/dev/terraform.tfvars` - Dev environment defaults
- `terraform/envs/dev/main.tf` - Composes all 7 modules with Cosmos Serverless and B1ms PostgreSQL
- `terraform/envs/dev/outputs.tf` - 23 outputs covering all module surfaces
- `terraform/envs/staging/providers.tf` - Identical provider config to dev
- `terraform/envs/staging/backend.tf` - Remote state backend targeting staaptfstatestg
- `terraform/envs/staging/variables.tf` - Root variables (default environment = "staging")
- `terraform/envs/staging/terraform.tfvars` - Staging environment defaults
- `terraform/envs/staging/main.tf` - Cosmos Serverless, B2ms PostgreSQL (64 GB storage)
- `terraform/envs/staging/outputs.tf` - Identical outputs to dev
- `terraform/envs/prod/providers.tf` - Identical provider config to dev
- `terraform/envs/prod/backend.tf` - Remote state backend targeting staaptfstateprod
- `terraform/envs/prod/variables.tf` - Root variables (default environment = "prod")
- `terraform/envs/prod/terraform.tfvars` - Prod environment defaults
- `terraform/envs/prod/main.tf` - Provisioned Cosmos (4000 RU/s, westus2 secondary), GP_Standard_D4s_v3 PostgreSQL (128 GB), model_capacity=30
- `terraform/envs/prod/outputs.tf` - Identical outputs to dev

## Decisions Made
- Dev/staging use Cosmos DB Serverless; prod uses Provisioned Autoscale with multi-region (westus2 secondary) — aligns with cost optimization for non-prod
- PostgreSQL tiered by environment: dev B_Standard_B1ms (32 GB), staging B_Standard_B2ms (64 GB), prod GP_Standard_D4s_v3 (128 GB) — General Purpose needed for prod workloads
- Foundry model_capacity left at default (10) for dev/staging; set to 30 for prod — higher TPM required for production agent traffic
- All environments share identical provider, output, and variable structures — only module parameter values differ, minimizing env drift risk

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 3 environments (dev, staging, prod) ready for terraform init && terraform plan
- Plan 05 (CI/CD pipeline) can now wire GitHub Actions to run terraform plan on PR and terraform apply on merge
- Each environment backend requires the corresponding Azure Storage account to be pre-provisioned before terraform init

---
*Phase: 01-foundation*
*Completed: 2026-03-26*
