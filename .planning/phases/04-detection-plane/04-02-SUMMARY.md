---
phase: 04-detection-plane
plan: "02"
subsystem: detection
tags: [kql, fabric, eventhouse, python, classification, domain-routing]

# Dependency graph
requires:
  - phase: 04-01
    provides: Fabric Eventhouse, Event Hub namespace, KQL database provisioned via Terraform
provides:
  - Three-table KQL pipeline: RawAlerts → EnrichedAlerts → DetectionResults
  - KQL classify_domain() function mapping ARM resource_type to AAP domain
  - KQL update policies with IsTransactional=false on hop 1 (data loss prevention)
  - KQL retention policies: 7d/30d/90d per table
  - Python classify_domain() mirror with identical mappings to KQL version
  - services/detection-plane/ Python package with pyproject.toml and test scaffolding
  - 31 unit tests for classify_domain() covering exact/prefix/case-insensitive/fallback
affects: [04-03, 04-04, phase-05-triage-remediation]

# Tech tracking
tech-stack:
  added: [KQL (Fabric Eventhouse), aap-detection-plane Python package, pytest-asyncio]
  patterns: [three-table KQL pipeline, update policy chaining, Python mirror of KQL logic]

key-files:
  created:
    - fabric/kql/schemas/raw_alerts.kql
    - fabric/kql/schemas/enriched_alerts.kql
    - fabric/kql/schemas/detection_results.kql
    - fabric/kql/functions/classify_domain.kql
    - fabric/kql/functions/enrich_alerts.kql
    - fabric/kql/functions/classify_alerts.kql
    - fabric/kql/policies/update_policies.kql
    - fabric/kql/retention/retention_policies.kql
    - services/detection-plane/__init__.py
    - services/detection-plane/classify_domain.py
    - services/detection-plane/pyproject.toml
    - services/detection-plane/tests/__init__.py
    - services/detection-plane/tests/unit/__init__.py
    - services/detection-plane/tests/integration/__init__.py
    - services/detection-plane/tests/unit/test_classify_domain.py
  modified: []

key-decisions:
  - "IsTransactional=false on hop 1 (RawAlerts->EnrichedAlerts): prevents data loss if enrichment fails; raw alert is always preserved"
  - "IsTransactional=true on hop 2 (EnrichedAlerts->DetectionResults): classify_domain() always succeeds (sre fallback), so this hop never fails"
  - "Python classify_domain() uses exact match first, then prefix match for broad categories (e.g., microsoft.security/alerts)"
  - "DETECT-007 satisfied by architecture: suppressed alerts never reach Event Hub; no code needed"

patterns-established:
  - "KQL three-table pipeline pattern: landing → enriched → classified with update policies"
  - "Python mirror pattern: Python implementation of KQL function for unit testing and fallback"
  - "SRE fallback domain (D-06): all unrecognized ARM resource types route to SRE agent"

requirements-completed: [DETECT-002, DETECT-007]

# Metrics
duration: 15min
completed: 2026-03-26
---

# Plan 04-02: KQL Pipeline — Table Schemas, classify_domain(), Update Policies

**Three-table KQL pipeline (RawAlerts→EnrichedAlerts→DetectionResults) with classify_domain() routing 25+ ARM resource types to 6 agent domains, Python mirror, and 31 unit tests**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-26T00:00:00Z
- **Completed:** 2026-03-26T00:15:00Z
- **Tasks:** 5
- **Files modified:** 15

## Accomplishments
- Three KQL table schemas defining the complete detection pipeline data model
- KQL classify_domain() function routing 25+ ARM resource types to 6 domains (compute/network/storage/security/arc/sre)
- KQL update policies with deliberate IsTransactional=false on hop 1 to prevent raw alert data loss on enrichment failure
- Python classify_domain() mirror with identical mappings, exact + prefix matching, case-insensitive
- 31 unit tests covering all classification paths — 31/31 passing

## Task Commits

Each task was committed atomically:

1. **Task 4-02-01: KQL Table Schemas** - `754aa79` (feat)
2. **Task 4-02-02: KQL classify_domain() Function** - `8ec24fe` (feat)
3. **Task 4-02-03: EnrichAlerts(), ClassifyAlerts(), Update + Retention Policies** - `9e77e76` (feat)
4. **Task 4-02-04: Python Detection Service Package** - `3a4f8c5` (feat)
5. **Task 4-02-05: classify_domain() Unit Tests** - `89efd67` (test)

## Files Created/Modified
- `fabric/kql/schemas/raw_alerts.kql` — Landing table for Event Hub ingestion (Common Alert Schema)
- `fabric/kql/schemas/enriched_alerts.kql` — Resource-enriched alerts (name, location, tags)
- `fabric/kql/schemas/detection_results.kql` — Classified alerts ready for Activator trigger
- `fabric/kql/functions/classify_domain.kql` — ARM resource_type → AAP domain mapping (KQL)
- `fabric/kql/functions/enrich_alerts.kql` — Update policy function: RawAlerts → EnrichedAlerts
- `fabric/kql/functions/classify_alerts.kql` — Update policy function: EnrichedAlerts → DetectionResults
- `fabric/kql/policies/update_policies.kql` — Chained update policies with IsTransactional commentary
- `fabric/kql/retention/retention_policies.kql` — 7d/30d/90d retention per table
- `services/detection-plane/__init__.py` — Package marker
- `services/detection-plane/classify_domain.py` — Python mirror of KQL classify_domain()
- `services/detection-plane/pyproject.toml` — Package config with pythonpath=["."] for pytest
- `services/detection-plane/tests/__init__.py` — Test package marker
- `services/detection-plane/tests/unit/__init__.py` — Unit test package marker
- `services/detection-plane/tests/integration/__init__.py` — Integration test package marker
- `services/detection-plane/tests/unit/test_classify_domain.py` — 31 unit tests

## Decisions Made
- **IsTransactional=false on hop 1**: If EnrichAlerts() fails and IsTransactional=true, the source ingestion into RawAlerts is rolled back — causing data loss. Setting false ensures raw data is always preserved even if enrichment fails (Risk 6 mitigation from 04-RESEARCH.md).
- **Python prefix matching**: `microsoft.security` and `microsoft.azurearcdata` in KQL use `has_any` which does substring matching. The Python mirror implements an explicit prefix loop to replicate this behavior.
- **DETECT-007 by architecture**: Suppressed alerts never reach Event Hub because Azure Monitor processing rules suppress the Action Group invocation upstream. No code needed — documented in KQL comments.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- KQL pipeline schemas and functions ready for Fabric Eventhouse deployment (04-03)
- Python package structure ready for alert ingestion and dedup logic (04-03)
- Unit tests establish the test pattern for 04-04 integration test suite
- DETECT-007 architecture note documented; test_first_hop_is_non_transactional() test needed in 04-04

---
*Phase: 04-detection-plane*
*Completed: 2026-03-26*
