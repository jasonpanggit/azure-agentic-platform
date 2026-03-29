---
phase: 8
slug: azure-validation-incident-simulation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-29
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Playwright (`@playwright/test`) for E2E; Python (`pytest`) for simulation scripts |
| **Config file** | `e2e/playwright.config.ts` (E2E); `scripts/simulate-incidents/requirements.txt` (simulation) |
| **Quick run command** | `cd e2e && npx playwright test --project=chromium e2e-incident-flow` |
| **Full suite command** | `cd e2e && npx playwright test` and `cd scripts/simulate-incidents && bash run-all.sh` |
| **Estimated runtime** | ~300 seconds (E2E: ~180s, simulation: ~120s with 120s timeouts per scenario) |

---

## Sampling Rate

- **After every task commit:** Run `cd e2e && npx playwright test --project=chromium e2e-incident-flow`
- **After every plan wave:** Run full E2E suite + simulation `run-all.sh`
- **Before `/gsd:verify-work`:** Full suite (E2E + simulation + OTel spot-check) must be green
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | AGENT-001 | CLI smoke | `az containerapp show -n ca-api-gateway-prod --query properties.configuration.secrets` | ✅ | ⬜ pending |
| 08-01-02 | 01 | 1 | AGENT-008 | CLI smoke | `az role assignment list --assignee 69e05934-... --scope /subscriptions/... \| grep "Azure AI Developer"` | ✅ | ⬜ pending |
| 08-01-03 | 01 | 1 | TEAMS-001 | CLI smoke | `az bot show -n aap-teams-bot-prod -g rg-aap-prod` | ✅ | ⬜ pending |
| 08-02-01 | 02 | 1 | E2E-002 | E2E | `cd e2e && npx playwright test e2e-incident-flow` | ✅ | ⬜ pending |
| 08-02-02 | 02 | 1 | E2E-003 | E2E | `cd e2e && npx playwright test e2e-hitl-approval` | ✅ | ⬜ pending |
| 08-02-03 | 02 | 1 | E2E-004 | E2E | `cd e2e && npx playwright test e2e-rbac` | ✅ | ⬜ pending |
| 08-02-04 | 02 | 1 | E2E-005 | E2E | `cd e2e && npx playwright test e2e-sse-reconnect` | ✅ | ⬜ pending |
| 08-03-01 | 03 | 2 | DETECT-004 | simulation | `cd scripts/simulate-incidents && python scenario_compute.py` | ❌ W0 | ⬜ pending |
| 08-03-02 | 03 | 2 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_network.py` | ❌ W0 | ⬜ pending |
| 08-03-03 | 03 | 2 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_storage.py` | ❌ W0 | ⬜ pending |
| 08-03-04 | 03 | 2 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_security.py` | ❌ W0 | ⬜ pending |
| 08-03-05 | 03 | 2 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_arc.py` | ❌ W0 | ⬜ pending |
| 08-03-06 | 03 | 2 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_sre.py` | ❌ W0 | ⬜ pending |
| 08-03-07 | 03 | 2 | DETECT-004 | simulation | `cd scripts/simulate-incidents && python scenario_cross.py` | ❌ W0 | ⬜ pending |
| 08-04-01 | 04 | 2 | MONITOR-007 | manual | App Insights Transaction Search shows `foundry.*`, `mcp.*`, `agent.*` spans | n/a | ⬜ pending |
| 08-04-02 | 04 | 2 | TEAMS-001 | E2E | `cd e2e && npx playwright test e2e-teams-roundtrip` | ❌ W0 | ⬜ pending |
| 08-05-01 | 05 | 3 | All | manual | `cat .planning/phases/08-azure-validation-incident-simulation/08-VALIDATION-REPORT.md` has no OPEN BLOCKING rows | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/simulate-incidents/common.py` — SimulationClient, cleanup_incident, auth utilities
- [ ] `scripts/simulate-incidents/requirements.txt` — azure-cosmos, azure-identity, requests
- [ ] `e2e/e2e-teams-roundtrip.spec.ts` — stub with `test.skip()` until Bot registration complete

*Wave 0 creates the file scaffolding; Wave 1 (Plan 01) removes skips and activates real assertions.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| OTel spans appear in App Insights | MONITOR-007, AUDIT-001 | Azure Portal access required; no CLI equivalent for span search | Azure Portal → Application Insights → Transaction Search → filter by `customDimensions["foundry.thread_id"]` |
| Teams Adaptive Card renders correctly | TEAMS-003 | Visual card rendering requires Teams client | Send high-risk approval scenario; inspect card in Teams channel |
| VALIDATION-REPORT.md has no OPEN BLOCKING | Phase 8 completion gate | Report is generated during execution, not pre-existing | `grep "OPEN" 08-VALIDATION-REPORT.md | grep "BLOCKING"` must return empty |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (common.py, e2e-teams-roundtrip.spec.ts)
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
