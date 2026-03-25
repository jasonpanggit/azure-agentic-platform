# Phase 1: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 01-foundation
**Areas discussed:** Terraform module structure, Workspace vs. directory strategy, State backend design, CI depth for Phase 1

---

## Terraform Module Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Flat root module | Everything in one root module. Simple to start, harder to maintain as the platform grows. One `terraform apply` provisions all resources. | |
| Per-domain modules | Separate subdirectories for networking/, foundry/, databases/, compute-env/, each with their own state. Teams can own domains. | ✓ |
| Root + child modules | Root module that calls reusable child modules. Single state, but code is organized. Middle ground. | |

**User's choice:** Per-domain modules

---

| Option | Description | Selected |
|--------|-------------|----------|
| Flat domain dirs (e.g. terraform/networking/) | Each domain dir is an independently-applyable root. Most explicit, cleanest CI targeting. | |
| Root with local modules | Reusable modules called from a single root. Simpler apply, but one state file for all. | |
| You decide | Use whatever the Terraform community considers idiomatic for this kind of platform. | ✓ |

**User's choice:** Claude's discretion on internal layout

---

## Workspace vs. Directory Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Terraform workspaces | One set of .tf files, `terraform workspace select dev/prod`. Simpler code but workspaces share backend config. | |
| Directory-per-environment | envs/dev/, envs/prod/, envs/staging/ each with their own backend.tf and tfvars. Explicit. | ✓ |
| Tfvars files only | Single root with `terraform.tfvars.dev` etc. passed via -var-file in CI. | |

**User's choice:** Directory-per-environment

---

| Option | Description | Selected |
|--------|-------------|----------|
| envs/ calls shared modules | envs/dev/ calls terraform/modules/* with dev.tfvars. Each env is its own Terraform root. | ✓ |
| Full copy per environment | Each environment directory has its own full copy of .tf files. | |
| Claude's discretion | | |

**User's choice:** envs/ calls shared modules

---

## State Backend Design

| Option | Description | Selected |
|--------|-------------|----------|
| One storage account per environment | Complete blast radius isolation. Separate accounts per env. | ✓ |
| Shared account, per-env containers | One shared storage account, separate blob containers per environment. | |
| Claude's discretion | | |

**User's choice:** One storage account per environment

---

| Option | Description | Selected |
|--------|-------------|----------|
| Entra auth / OIDC (no storage keys) | `use_oidc = true` with Entra workload identity in CI. No storage access keys anywhere. | ✓ |
| Storage access key | Storage account access key stored as GitHub secret. Simpler setup. | |
| Claude's discretion | | |

**User's choice:** Entra auth / OIDC (no storage keys)

---

## CI Depth for Phase 1

| Option | Description | Selected |
|--------|-------------|----------|
| Plan on PR + Apply on merge | Two workflows: terraform-plan.yml on PR, terraform-apply.yml on merge to main. | ✓ |
| Combined single workflow | One workflow that does plan on PR and apply on merge. | |
| Plan + Apply + drift detection + PR comments | Full suite including scheduled drift detection job. | |

**User's choice:** Plan on PR + Apply on merge (two separate workflows)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include required_tags check in Phase 1 | required_tags policy lint in the plan workflow. Untagged resources fail CI. | ✓ |
| No, defer tagging lint to later | Keep Phase 1 CI minimal. | |

**User's choice:** Yes — include required_tags check in Phase 1 CI

---

## Claude's Discretion

- Internal Terraform module layout within each domain directory
- Exact naming conventions for Azure resources
- Key Vault initial setup details (seeding deferred to Phase 2)
- NSG rule specifics
- Cosmos DB partition key design

## Deferred Ideas

None — discussion stayed within Phase 1 scope.
