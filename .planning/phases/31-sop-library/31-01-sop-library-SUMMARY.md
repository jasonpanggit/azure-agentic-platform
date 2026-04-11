---
phase: 31-sop-library
plan: 01
subsystem: sops
tags: [sop, markdown, yaml, lint, pyyaml, pytest, hitl, runbook]

# Dependency graph
requires:
  - phase: 30-sop-engine
    provides: [sops PostgreSQL table, upload_sops.py script, SOP_VECTOR_STORE_ID env var support]
provides:
  - 34 production-quality SOP markdown files covering 9 domains
  - scripts/lint_sops.py — SOP YAML front matter and section validator
  - scripts/tests/test_lint_sops.py — 6 lint unit tests
  - scripts/tests/test_sop_library_coverage.py — 36 coverage tests (34 parametrized + lint + count)
  - sops/_schema/sop-template.md — canonical authoring template
  - sops/_schema/README.md — authoring guide
affects: [phase-32, phase-33, sop-engine, orchestrator, domain-agents]

# Tech tracking
tech-stack:
  added: []
  patterns: [sop-schema, yaml-front-matter, step-type-labels, hitl-remediation]

key-files:
  created:
    - scripts/lint_sops.py
    - scripts/tests/test_lint_sops.py
    - scripts/tests/test_sop_library_coverage.py
    - sops/_schema/sop-template.md
    - sops/_schema/README.md
    - sops/compute/vm-high-cpu.md
    - sops/compute/vm-memory-pressure.md
    - sops/compute/vm-disk-exhaustion.md
    - sops/compute/vm-unavailable.md
    - sops/compute/vm-boot-failure.md
    - sops/compute/vm-network-unreachable.md
    - sops/compute/compute-generic.md
    - sops/arc/arc-vm-disconnected.md
    - sops/arc/arc-vm-extension-failure.md
    - sops/arc/arc-vm-patch-gap.md
    - sops/arc/arc-generic.md
    - sops/vmss/vmss-scale-failure.md
    - sops/vmss/vmss-unhealthy-instances.md
    - sops/vmss/vmss-generic.md
    - sops/aks/aks-node-not-ready.md
    - sops/aks/aks-pod-crashloop.md
    - sops/aks/aks-upgrade-required.md
    - sops/aks/aks-generic.md
    - sops/patch/patch-compliance-violation.md
    - sops/patch/patch-installation-failure.md
    - sops/patch/patch-critical-missing.md
    - sops/patch/patch-generic.md
    - sops/eol/eol-os-detected.md
    - sops/eol/eol-runtime-detected.md
    - sops/eol/eol-generic.md
    - sops/network/nsg-blocking.md
    - sops/network/connectivity-failure.md
    - sops/network/network-generic.md
    - sops/security/security-defender-alert.md
    - sops/security/security-rbac-anomaly.md
    - sops/security/security-generic.md
    - sops/sre/sre-slo-breach.md
    - sops/sre/sre-availability-degraded.md
    - sops/sre/sre-generic.md
  modified: []

key-decisions:
  - "Followed full plan's schema (Description, Triage Steps, Remediation Steps, Escalation, Rollback, References) with step labels [DIAGNOSTIC], [NOTIFY], [DECISION], [REMEDIATION:*] rather than GSD wrapper's alternative labels"
  - "Every domain gets a -generic.md fallback SOP for incidents that don't match specific scenarios"
  - "VMSS and AKS SOPs use domain: compute since tools live on compute agent"
  - "EOL SOPs are advisory-only — no ARM actions, only NOTIFY and REMEDIATION:LOW with acknowledgment"
  - "Security SOPs auto-escalate to security team — no automated remediation for security incidents"

patterns-established:
  - "SOP authoring pattern: YAML front matter (title, domain, version, scenario_tags, severity_threshold, resource_types, is_generic) + 6 required sections"
  - "Step type labels: [DIAGNOSTIC], [NOTIFY], [DECISION], [REMEDIATION:LOW/MEDIUM/HIGH/CRITICAL], [ESCALATE]"
  - "HITL pattern: remediation steps use [REMEDIATION:*] with explicit approval messages, never ARM calls"
  - "Generic fallback SOP: each domain has a {domain}-generic.md with is_generic: true for unmatched incidents"
  - "Lint-before-upload workflow: python3 scripts/lint_sops.py sops/ must pass before upload_sops.py"

requirements-completed: []

# Metrics
duration: 12min
completed: 2026-04-11
---

# Phase 31: SOP Library Summary

**34 production-quality SOP markdown files across 9 domains with YAML front matter validation, lint tooling, and parametrized coverage tests**

## Performance

- **Duration:** 12 min
- **Tasks:** 5 chunks (9 tasks)
- **Files created:** 39

## Accomplishments
- Authored 34 SOP files covering all 9 platform domains (compute 7, arc 4, vmss 3, aks 4, patch 4, eol 3, network 3, security 3, sre 3)
- Created scripts/lint_sops.py with YAML front matter validation, required section checks, and resource_types enforcement for non-generic SOPs
- All 34 SOPs pass lint validation with 0 errors
- 42 new tests (6 lint unit tests + 36 coverage tests) all passing

## Task Commits

Each chunk was committed atomically:

1. **Chunk 1: SOP schema template + lint tool + tests** - `f083067` (feat)
2. **Chunk 2: 7 compute domain SOPs** - `b1f7af5` (feat)
3. **Chunk 3: Arc (4) + VMSS (3) + AKS (4) SOPs** - `b736eac` (feat)
4. **Chunk 4: Patch (4) + EOL (3) + Network (3) + Security (3) + SRE (3) SOPs** - `1375fb6` (feat)
5. **Chunk 5: SOP library coverage test** - `662ba23` (test)

## Files Created/Modified

### Schema & Tooling
- `sops/_schema/sop-template.md` - Canonical SOP authoring template with all required sections and step labels
- `sops/_schema/README.md` - Authoring guide with step type label reference
- `scripts/lint_sops.py` - Validates YAML front matter fields, required sections, resource_types for non-generic SOPs
- `scripts/tests/test_lint_sops.py` - 6 unit tests: valid SOP passes, missing front matter/title/domain/sections/resource_types fail
- `scripts/tests/test_sop_library_coverage.py` - 36 tests: 34 parametrized file existence checks + lint pass + count >= 34

### SOP Files (34 total)
- `sops/compute/` - 7 files: vm-high-cpu, vm-memory-pressure, vm-disk-exhaustion, vm-unavailable, vm-boot-failure, vm-network-unreachable, compute-generic
- `sops/arc/` - 4 files: arc-vm-disconnected, arc-vm-extension-failure, arc-vm-patch-gap, arc-generic
- `sops/vmss/` - 3 files: vmss-scale-failure, vmss-unhealthy-instances, vmss-generic
- `sops/aks/` - 4 files: aks-node-not-ready, aks-pod-crashloop, aks-upgrade-required, aks-generic
- `sops/patch/` - 4 files: patch-compliance-violation, patch-installation-failure, patch-critical-missing, patch-generic
- `sops/eol/` - 3 files: eol-os-detected, eol-runtime-detected, eol-generic
- `sops/network/` - 3 files: nsg-blocking, connectivity-failure, network-generic
- `sops/security/` - 3 files: security-defender-alert, security-rbac-anomaly, security-generic
- `sops/sre/` - 3 files: sre-slo-breach, sre-availability-degraded, sre-generic

## Decisions Made
- Followed the full plan's schema structure (not the GSD wrapper's alternative section/label names) since the full plan has exact content
- VMSS and AKS SOPs set `domain: compute` because VMSS/AKS tools are on the compute agent
- Every domain gets a `-generic.md` fallback SOP (is_generic: true) for unmatched incidents
- Security SOPs escalate immediately with critical severity — no automated ARM actions
- EOL SOPs are advisory-only with REMEDIATION:LOW — no ARM actions, only notification/acknowledgment

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
- **Post-deploy:** Run `python scripts/upload_sops.py` with `AZURE_PROJECT_ENDPOINT` and `DATABASE_URL` to upload SOPs to Foundry vector store and PostgreSQL metadata table
- **Terraform:** Set `sop_vector_store_id` in `terraform/envs/prod/terraform.tfvars` from `.env.sops` output after upload

## Next Phase Readiness
- 34 SOPs ready for vector store upload via `scripts/upload_sops.py` (Phase 30 script)
- Lint tooling validates any new SOPs added in future phases
- Coverage test enforces minimum 34 SOPs — future additions auto-tracked by adding to REQUIRED_FILES list

---
*Phase: 31-sop-library*
*Completed: 2026-04-11*
