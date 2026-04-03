# Phase 21: Detection Plane Activation - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Enable the live detection loop in production. The Fabric Eventhouse + Activator infrastructure was built in Phase 4 and is complete in Terraform — it is currently disabled via `enable_fabric_data_plane = false` in `terraform/envs/prod/main.tf` (line 344). This phase activates, validates, and operationalises the existing pipeline against real Azure Monitor alerts. No simulation scripts required after this phase.

**Requirement:** PROD-004 — Live alert detection loop operational without simulation scripts.

**What this phase does NOT do:**
- Does not add new Terraform resources (Fabric module already exists in `terraform/modules/fabric/`)
- Does not change detection pipeline logic (services/detection-plane/ is complete from Phase 4)
- Does not add new API endpoints

**What this phase DOES:**
1. Flip `enable_fabric_data_plane = false → true` in `terraform/envs/prod/main.tf`
2. Document the post-`terraform apply` manual steps (Activator trigger, OneLake mirror) in an operator runbook
3. Create validation scripts to verify the pipeline is live
4. Create a smoke-test that injects a real Azure Monitor alert and asserts it reaches the agent platform without simulation scripts

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure activation phase. Use the existing Phase 4 patterns from:
- `terraform/modules/fabric/main.tf` — all Fabric resources controlled by `enable_fabric_data_plane` flag
- `services/detection-plane/` — existing pipeline code is complete
- `terraform/envs/prod/main.tf` — single flag change required
- `.planning/phases/04-detection-plane/` — Phase 4 plans contain the full pipeline design

Key constraints:
- Activator trigger wiring is **manual-only** (Fabric portal) — cannot be automated via Terraform or REST API
- OneLake mirror is **manual-only** — see existing reminder in fabric module
- Post-apply validation should use existing KQL patterns from Phase 4

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `terraform/modules/fabric/main.tf` — Full Fabric module, all resources gated by `enable_fabric_data_plane`
- `services/detection-plane/` — Complete pipeline: classify_domain.py, dedup.py, alert_state.py, payload_mapper.py, models.py
- `services/detection-plane/docs/AUDIT-003-onelake-setup.md` — Existing OneLake setup guide (if present)
- `scripts/ops/` — Pattern for operator runbooks (see 19-3, 19-4, 19-5 for style reference)

### Established Patterns
- Operator runbooks: `scripts/ops/NN-N-*.sh` with pre-flight checks, step-by-step instructions, validation
- Validation scripts: use Azure CLI + KQL queries to verify infra state
- Phase smoke tests: inject synthetic events, assert they flow through the pipeline

### Integration Points
- `terraform/envs/prod/main.tf` line 344 — single flag to flip
- `POST /api/v1/incidents` — endpoint the Activator User Data Function calls
- `services/detection-plane/tests/` — existing unit tests for pipeline logic

</code_context>

<specifics>
## Specific Ideas

- The `null_resource.activator_setup_reminder` in `terraform/modules/fabric/main.tf` already echoes the exact manual steps needed — the operator runbook should expand on these
- Validation should query Eventhouse KQL tables (`RawAlerts`, `EnrichedAlerts`, `DetectionResults`) to confirm pipeline health
- PROD-004 success criterion: zero simulation scripts in the pipeline after this phase

</specifics>

<deferred>
## Deferred Ideas

None — pure infrastructure activation phase. All complex detection logic was built in Phase 4.

</deferred>

---

*Phase: 21-detection-plane-activation*
*Context gathered: 2026-04-03 via autonomous mode (infrastructure phase)*
