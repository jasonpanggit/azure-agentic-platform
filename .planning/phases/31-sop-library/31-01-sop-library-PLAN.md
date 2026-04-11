---
id: "31-01"
phase: 31
plan: 1
wave: 1
title: "SOP Library — All Chunks"
objective: "Author ≥34 production-quality SOP markdown files covering all domains (compute, arc, vmss, aks, patch, eol, network, security, sre), validate them with a lint script, create the sops/ directory structure, and run scripts/upload_sops.py to populate the Foundry vector store and PostgreSQL metadata table."
autonomous: true
gap_closure: false
files_modified:
  - "sops/_schema/sop-template.md"
  - "scripts/lint_sops.py"
  - "tests/test_sop_lint.py"
  - "sops/compute/vm-high-cpu.md"
  - "sops/compute/vm-high-memory.md"
  - "sops/compute/vm-disk-full.md"
  - "sops/compute/vm-unreachable.md"
  - "sops/compute/vm-boot-failure.md"
  - "sops/compute/vm-nic-misconfigured.md"
  - "sops/compute/vm-extension-failure.md"
  - "sops/arc/arc-agent-offline.md"
  - "sops/arc/arc-guest-config-drift.md"
  - "sops/arc/arc-extension-stuck.md"
  - "sops/vmss/vmss-scale-failure.md"
  - "sops/vmss/vmss-unhealthy-instances.md"
  - "sops/aks/aks-node-not-ready.md"
  - "sops/aks/aks-pod-crashloop.md"
  - "sops/patch/patch-assessment-stale.md"
  - "sops/patch/patch-installation-failed.md"
  - "sops/eol/os-eol-approaching.md"
  - "sops/eol/software-eol-detected.md"
  - "sops/network/nsg-blocking-traffic.md"
  - "sops/network/vnet-peering-broken.md"
  - "sops/network/load-balancer-unhealthy.md"
  - "sops/network/expressroute-degraded.md"
  - "sops/security/defender-alert-high.md"
  - "sops/security/keyvault-access-denied.md"
  - "sops/security/rbac-change-detected.md"
  - "sops/security/policy-noncompliance.md"
  - "sops/sre/slo-breach.md"
  - "sops/sre/error-budget-exhausted.md"
  - "sops/sre/service-health-degraded.md"
  - "sops/sre/advisor-high-impact.md"
  - "sops/sre/change-analysis-anomaly.md"
  - "tests/test_sop_library_coverage.py"
task_count: 45
key_links: []
---

# Phase 31: SOP Library — Implementation Plan

> **IMPORTANT**: This is a GSD wrapper plan. The full detailed implementation plan is at:
> `docs/superpowers/plans/2026-04-11-phase-31-sop-library.md`
>
> **Read that file first.** Execute all 5 chunks in order:
> 1. Chunk 1: SOP Schema Template + Lint Tool
> 2. Chunk 2: SOP Library — Compute Domain (7 files)
> 3. Chunk 3: SOP Library — Arc, VMSS, AKS Domains
> 4. Chunk 4: SOP Library — Patch, EOL, Network, Security, SRE Domains
> 5. Chunk 5: Validate Full Library and Upload

## Goal

Author ≥34 production-quality SOP markdown files covering all domains, validate them for schema compliance, create the `sops/` directory structure, and run `scripts/upload_sops.py` to populate the Foundry vector store and PostgreSQL metadata table.

## Architecture

All SOP files live under `sops/` in the repo root, following the template in `sops/_schema/sop-template.md`. A lint script (`scripts/lint_sops.py`) validates each file's YAML front matter, required sections, and step type labels. Files are grouped by domain. After lint passes, `scripts/upload_sops.py` (Phase 30) uploads them to Foundry and registers metadata in PostgreSQL.

## SOP File Schema

Each SOP markdown file must have YAML front matter with:
- `title`: string
- `domain`: string (compute|arc|vmss|aks|patch|eol|network|security|sre)
- `resource_type`: string
- `scenario_tags`: list of strings
- `severity`: string (critical|high|medium|low)
- `version`: string (e.g. "1.0")

Required sections: `## Symptoms`, `## Diagnosis Steps`, `## Remediation Steps`, `## Escalation Criteria`

Each step must be labeled with type: `[DIAGNOSE]`, `[PROPOSE]`, `[NOTIFY]`, `[DOCUMENT]`

## Key Technical Notes

- `scripts/lint_sops.py` validates YAML front matter + required sections + step labels
- `tests/test_sop_lint.py` uses pytest parametrize over all 34+ SOP file paths
- `tests/test_sop_library_coverage.py` checks all expected files exist
- SOP files DO NOT execute ARM calls — all remediation steps use `[PROPOSE]` label
- `scripts/upload_sops.py` is called after lint passes (Phase 30 script, dry-run mode for tests)

## Success Criteria

- [ ] `sops/_schema/sop-template.md` exists
- [ ] `scripts/lint_sops.py` validates all required fields
- [ ] ≥34 SOP files exist across 9 domains
- [ ] All SOP files pass lint validation
- [ ] `tests/test_sop_library_coverage.py` passes (all expected files present)
- [ ] Lint test suite passes
