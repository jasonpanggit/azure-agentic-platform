# Plan 21-2 Summary: Validation & Operator Runbook

**Status:** COMPLETE
**Phase:** 21 — Detection Plane Activation
**Wave:** 2
**Completed:** 2026-04-03

---

## What Was Built

### Task 21-2-01 + 21-2-03: Operator Runbook Script

**File:** `scripts/ops/21-2-activate-detection-plane.sh`

Interactive bash script guiding an operator through the complete detection plane activation workflow. Structured as 8 phases:

- **Phase 0:** Pre-flight terraform plan verification — asserts 5 `fabric_*` azapi_resource creates + 2 `null_resource` creates; safety guard warns if more than 7 resources change
- **Pre-flight:** `az account show` login check + subscription verification
- **Step 1:** Verify 5 Fabric resources provisioned (workspace, Eventhouse, KQL DB, Activator, Lakehouse) via `az rest`
- **Step 2:** Eventstream connector setup — Event Hub `ehns-aap-prod/eh-alerts-prod` → Eventhouse `kqldb-aap-prod` table `RawAlerts`; includes `az eventhubs` command to retrieve connection string
- **Step 3:** KQL table schema for `RawAlerts`, `EnrichedAlerts`, `DetectionResults` — ready to paste into Fabric query editor
- **Step 4:** Activator trigger wiring — condition `domain IS NOT NULL`, action `handle_activator_trigger` User Data Function; references `null_resource.activator_setup_reminder` in Terraform
- **Step 5:** OneLake mirror setup summary with AUDIT-003 retention requirement (≥730 days); references `AUDIT-003-onelake-setup.md`
- **Step 6:** Validation KQL queries — `RawAlerts | count`, `EnrichedAlerts` pipeline health, `DetectionResults` classification sample, domain volume summary
- **Step 7:** End-to-end smoke test — fire test alert, wait 60s, verify `DetectionResults`, verify `det-` prefixed incident at API gateway
- **PROD-004 checklist** — 8 checkbox items covering all activation gates

All acceptance criteria pass: valid bash syntax, executable, contains all required markers.

### Task 21-2-02: Operator Documentation

**File:** `docs/ops/detection-plane-activation.md`

Comprehensive operator guide with:
- Architecture ASCII diagram: Azure Monitor → Event Hub → Eventhouse → Activator → API → Orchestrator
- Prerequisites table (Phase 19 complete, terraform apply, Fabric capacity active, Event Hub provisioned, API gateway healthy)
- Full step-by-step procedure cross-referencing the runbook script
- **Domain Classification Reference** — complete table of all 27 ARM resource type mappings from `classify_domain.py` across 5 domains (compute, network, storage, security, arc) + sre fallback
- **Troubleshooting** — 5 failure modes with root cause checks and remediation commands
- **Rollback** procedure — `enable_fabric_data_plane = false` + targeted `terraform apply`
- PROD-004 verification checklist

---

## Acceptance Criteria Results

### Task 21-2-01 (script)

| Check | Result |
|---|---|
| `head -1` outputs `#!/usr/bin/env bash` | ✅ |
| `grep "set -euo pipefail"` | ✅ |
| `grep "RESOURCE_GROUP="` returns `rg-aap-prod` | ✅ |
| `grep "PROD-004"` ≥1 match | ✅ (2 matches) |
| `grep "RawAlerts"` ≥1 match | ✅ (8 matches) |
| `grep "EnrichedAlerts"` ≥1 match | ✅ (5 matches) |
| `grep "DetectionResults"` ≥1 match | ✅ (12 matches) |
| `grep "Activator"` ≥1 match | ✅ (11 matches) |
| `grep "OneLake"` ≥1 match | ✅ (9 matches) |
| `grep "domain IS NOT NULL"` ≥1 match | ✅ (2 matches) |
| `grep "det-"` ≥1 match | ✅ |
| `grep "az account show"` ≥1 match | ✅ (2 matches) |
| `test -x` exits 0 | ✅ |
| `bash -n` exits 0 | ✅ |

### Task 21-2-02 (docs)

| Check | Result |
|---|---|
| `grep "Detection Plane Activation"` | ✅ |
| `grep "Prerequisites"` | ✅ |
| `grep "enable_fabric_data_plane"` ≥1 match | ✅ (5 matches) |
| `grep "ehns-aap-prod"` ≥1 match | ✅ (5 matches) |
| `grep "classify_domain"` ≥1 match | ✅ (7 matches) |
| `grep "Troubleshooting"` | ✅ |
| `grep "Rollback"` | ✅ |
| `grep "21-2-activate-detection-plane"` ≥1 match | ✅ (3 matches) |

### Task 21-2-03 (terraform plan verification section)

| Check | Result |
|---|---|
| `grep "terraform.*plan"` | ✅ |
| `grep "fabric_workspace"` | ✅ |
| `grep "fabric_eventhouse"` | ✅ |
| `grep "fabric_kql_database"` | ✅ |
| `grep "fabric_activator"` | ✅ |
| `grep "fabric_lakehouse"` | ✅ |
| `grep "null_resource"` | ✅ |

---

## Commits

1. `feat(21-2): add detection plane operator runbook script` — `scripts/ops/21-2-activate-detection-plane.sh`
2. `docs(21-2): add detection plane activation operator guide` — `docs/ops/detection-plane-activation.md`

---

## Must-Haves Status

- [x] Operator runbook script at `scripts/ops/21-2-activate-detection-plane.sh` with pre-flight checks
- [x] Script includes Eventstream connector setup instructions
- [x] Script includes Activator trigger wiring instructions (domain IS NOT NULL condition)
- [x] Script includes OneLake mirror reference
- [x] Script includes KQL validation queries for RawAlerts, EnrichedAlerts, DetectionResults
- [x] Script includes end-to-end smoke test instructions (fire alert → verify in DetectionResults → verify det- prefix in Cosmos)
- [x] Script includes PROD-004 verification checklist
- [x] Operator documentation at `docs/ops/detection-plane-activation.md`
- [x] Documentation includes architecture diagram, troubleshooting, and rollback procedure
