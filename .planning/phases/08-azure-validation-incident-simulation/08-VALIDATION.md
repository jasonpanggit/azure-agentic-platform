---
phase: 8
slug: azure-validation-incident-simulation
status: ready
nyquist_compliant: true
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
| 08-01-01 | 01 | 1 | AGENT-001 | code check | `grep -- "--create" scripts/configure-orchestrator.py` | ✅ | ⬜ pending |
| 08-01-02 | 01 | 1 | AGENT-001 | CLI smoke | Script output shows `AGENT_ID=asst_` prefix when run | ✅ | ⬜ pending |
| 08-01-03 | 01 | 1 | AGENT-008 | CLI smoke | `az containerapp show -n ca-api-gateway-prod --query "properties.template.containers[0].env[?name=='ORCHESTRATOR_AGENT_ID'].value"` | ✅ | ⬜ pending |
| 08-01-04 | 01 | 1 | AGENT-008 | CLI smoke | `az role assignment list --assignee 69e05934-... \| grep "Azure AI Developer"` | ✅ | ⬜ pending |
| 08-01-05 | 01 | 1 | TEAMS-001 | CLI smoke | `az bot show -n aap-teams-bot-prod -g rg-aap-prod` | ✅ | ⬜ pending |
| 08-01-06 | 01 | 1 | CI-001 | CLI smoke | `gh secret list \| grep POSTGRES_ADMIN_PASSWORD` | ✅ | ⬜ pending |
| 08-02-01 | 02 | 2 | E2E-002 | E2E | `cd e2e && npx playwright test e2e-incident-flow` | ✅ | ⬜ pending |
| 08-02-02 | 02 | 2 | E2E-003 | E2E | `cd e2e && npx playwright test e2e-hitl-approval` | ✅ | ⬜ pending |
| 08-02-03 | 02 | 2 | E2E-004 | E2E | `cd e2e && npx playwright test e2e-rbac` | ✅ | ⬜ pending |
| 08-02-04 | 02 | 2 | E2E-005 | E2E | `cd e2e && npx playwright test e2e-sse-reconnect` | ✅ | ⬜ pending |
| 08-03-01 | 03 | 3 | DETECT-004 | simulation | `cd scripts/simulate-incidents && python scenario_compute.py` | ❌ W0 | ⬜ pending |
| 08-03-02 | 03 | 3 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_network.py` | ❌ W0 | ⬜ pending |
| 08-03-03 | 03 | 3 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && python scenario_storage.py` | ❌ W0 | ⬜ pending |
| 08-03-04 | 03 | 3 | E2E-001 | CI gate | `grep "run-all.sh" .github/workflows/staging-e2e-simulation.yml` | ✅ | ⬜ pending |
| 08-03-05 | 03 | 3 | TRIAGE-001 | simulation | `cd scripts/simulate-incidents && bash run-all.sh` | ❌ W0 | ⬜ pending |
| 08-04-01 | 04 | 3 | MONITOR-007 | code check | `grep "agent_span\|foundry_span\|mcp_span" services/api-gateway/instrumentation.py` | ❌ W0 | ⬜ pending |
| 08-04-02 | 04 | 3 | MONITOR-007 | manual | App Insights Transaction Search shows `foundry.*`, `mcp.*`, `agent.orchestrator` spans | n/a | ⬜ pending |
| 08-04-03 | 04 | 3 | TEAMS-001 | E2E | `cd e2e && npx playwright test e2e-teams-roundtrip` | ❌ W0 | ⬜ pending |
| 08-04-06 | 04 | 3 | DEPLOY | CLI smoke | `az containerapp revision list -n ca-api-gateway-prod -g rg-aap-prod` shows new revision | ✅ | ⬜ pending |
| 08-05-01 | 05 | 4 | All | manual | `cat .planning/phases/08-azure-validation-incident-simulation/08-VALIDATION-REPORT.md` has no OPEN BLOCKING rows | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/simulate-incidents/common.py` — SimulationClient, cleanup_incident, auth utilities
- [ ] `scripts/simulate-incidents/requirements.txt` — azure-cosmos, azure-identity, requests
- [ ] `e2e/e2e-teams-roundtrip.spec.ts` — scaffold with conditional return (no test.skip()) when BOT_APP_ID/BOT_APP_PASSWORD absent

*Wave 0 creates the file scaffolding; Wave 1 (Plan 01) removes skips and activates real assertions.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| OTel spans appear in App Insights | MONITOR-007, AUDIT-001 | Azure Portal access required; no CLI equivalent for span search | Azure Portal > Application Insights > Transaction Search > filter by operation name `agent.orchestrator`, `foundry.*`, `mcp.*` |
| Teams Adaptive Card renders correctly | TEAMS-003 | Visual card rendering requires Teams client | Send high-risk approval scenario; inspect card in Teams channel |
| VALIDATION-REPORT.md has no OPEN BLOCKING | Phase 8 completion gate | Report is generated during execution, not pre-existing | `grep "OPEN" 08-VALIDATION-REPORT.md | grep "BLOCKING"` must return empty |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (common.py, e2e-teams-roundtrip.spec.ts)
- [x] No watch-mode flags
- [x] Feedback latency < 300s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
