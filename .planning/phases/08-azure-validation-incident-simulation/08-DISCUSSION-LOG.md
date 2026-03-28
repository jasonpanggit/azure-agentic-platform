# Phase 8: Azure Validation & Incident Simulation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-29
**Phase:** 08-azure-validation-incident-simulation
**Areas discussed:** Validation scope & fix strategy, Incident simulation safety & approach, Issue log format & fix task structure, Deferred Phase 7 items to include

---

## Validation Scope & Fix Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Fix gaps + validate | Phase 8 both fixes provisioning gaps AND validates end-to-end. Fix tasks become part of the phase plans. Recommended — 260328-va0 report shows partial provisioning. | ✓ |
| Validate only — document gaps | Phase 8 only documents what's broken. No fixes. Produces a report and creates backlog for Phase 9. | |
| Fix-first, then validate (two-part) | First plan fixes provisioning, subsequent plans validate. Clear separation within the same phase. | |

**User's choice:** Fix gaps + validate (Recommended)
**Notes:** Platform is partially provisioned. Can't validate end-to-end until ORCHESTRATOR_AGENT_ID, Foundry RBAC, and Teams bot registration are complete.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Critical path + smoke tests | Validate full end-to-end: chat → detection → triage → HITL approval → Teams alert. Plus basic smoke tests on everything else. Recommended. | ✓ |
| All 72 requirements, deep | Deep-dive every requirement against deployed platform. Phase 7 E2E already covers most. | |
| Known gaps only + run Phase 7 E2E | Only the 3 PARTIAL and 1 PENDING items from 260328-va0 report, then run Phase 7 E2E suite against prod. | |

**User's choice:** Critical path + smoke tests (Recommended)
**Notes:** Matches the core platform value proposition. Phase 7 E2E tests run against prod as part of this.

---

## Incident Simulation Safety & Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Direct API injection (Recommended) | POST /api/v1/incidents with synthetic payload. No real Azure Monitor alert, no real resource affected. Full agent pipeline exercised. | ✓ |
| Real Azure Monitor alert end-to-end | Configure test alert rule targeting test VM, let it fire naturally through Event Hub → Eventhouse → Activator → agent. | |
| Mock server (UI-only validation) | Use existing mock server (run-mock.sh) to simulate agent responses, test only web UI and Teams surfaces. | |

**User's choice:** Direct API injection (Recommended)
**Notes:** Safest approach. No risk of cascading alerts or real resource modification.

---

| Option | Description | Selected |
|--------|-------------|----------|
| One per domain + one cross-domain (Recommended) | 7 scenarios total: compute, network, storage, security, arc, sre, plus one cross-domain (disk-full triggering compute + storage). | ✓ |
| 3 core scenarios only | VM high CPU, network NSG block, Arc connectivity loss. Fast, less coverage. | |
| Full scenario matrix (10+) | Edge cases: budget exceeded, stale approval, dedup, rate limiting, protected resource guard. | |

**User's choice:** One per domain + one cross-domain (Recommended)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-cleanup after each scenario (Recommended) | Delete Cosmos DB incident and approval records after asserting outcomes. Clean state for next run. | ✓ |
| Dedicated validation container, manual cleanup | Keep records in incidents-validation container. Cleanup is periodic/manual. | |
| Keep all records (audit trail) | No cleanup — simulation records accumulate. | |

**User's choice:** Auto-cleanup after each scenario (Recommended)

---

## Issue Log Format & Fix Task Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single VALIDATION-REPORT.md + GSD todos (Recommended) | One report in phase directory. Each finding → GSD todo via /gsd:add-backlog. | ✓ |
| Per-service issue files + index | One markdown file per service/component with summary index. More granular. | |
| GitHub Issues via gh CLI | GitHub Issues created during validation. Good for team tracking but adds noise. | |

**User's choice:** Single VALIDATION-REPORT.md + GSD todos (Recommended)

---

| Option | Description | Selected |
|--------|-------------|----------|
| 3-level: BLOCKING / DEGRADED / COSMETIC (Recommended) | BLOCKING = platform can't function; DEGRADED = feature broken; COSMETIC = minor issues. Fix all BLOCKING in Phase 8. | ✓ |
| Binary PASS/FAIL | Simpler but less actionable for prioritization. | |
| 5-level severity (Critical–Info) | Aligned with security standards. Heavy for an ops validation. | |

**User's choice:** 3-level: BLOCKING / DEGRADED / COSMETIC (Recommended)

---

## Deferred Phase 7 Items to Include

| Option | Description | Selected |
|--------|-------------|----------|
| Both: Teams E2E + manual OTel spans (Recommended) | Full Teams bot round-trip E2E via Bot Connector API + manual OTel spans for Foundry/MCP/agent calls. | ✓ |
| Teams E2E only | Skip observability improvement. | |
| Manual OTel spans only | Skip Teams E2E. | |
| Neither — stay focused on validation | Keep Phase 7 deferred items for a future ops hardening phase. | |

**User's choice:** Both: Teams E2E + manual OTel spans (Recommended)
**Notes:** Both were explicitly noted as Phase 8 candidates in Phase 7 CONTEXT.md deferred section.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Bot Connector API (true round-trip) | Use Teams Bot Connector API REST calls to the bot's service URL. Requires Messaging.Send permission. True round-trip. | ✓ |
| Extend Phase 7 Graph API approach | Extend existing Graph API verification. Simpler but not a true bot message send. | |
| Local bot + dev Teams tenant | Run bot locally in CI against dev tenant. Requires dev Teams app registration. | |

**User's choice:** Bot Connector API (true round-trip)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Foundry calls + MCP tool calls + agent invocations (Recommended) | Spans for create_thread/post_message/poll_response + MCP tool invocations + domain agent activations. | ✓ |
| Foundry API calls only | Most impactful for LLM latency understanding. | |
| Gateway request spans only | Entry point tracing without internal agent spans. | |

**User's choice:** Foundry calls + MCP tool calls + agent invocations (Recommended)

---

## Claude's Discretion

- Exact Foundry Orchestrator Agent creation script (CLI vs. Terraform vs. Python SDK)
- Teams Bot Connector API authentication flow details (exact header format, token endpoint)
- Python simulation script structure and assertion depth per scenario
- VALIDATION-REPORT.md table formatting details

## Deferred Ideas

- APIM Standard v2 — still deferred, no production traffic data
- Custom domain + TLS via Azure Front Door — still deferred from Phase 7
- Azure SRE Agent integration — future capability, out of scope for Phase 8
- Multi-subscription E2E with real secondary subscriptions — future ops hardening task
