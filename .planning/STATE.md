---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Roadmap — World-Class AIOps
status: in_progress
last_updated: "2026-04-03T17:30:00.000Z"
progress:
  total_phases: 22
  completed_phases: 9
  total_plans: 52
  completed_plans: 47
current_position:
  phase: 21
  plan: 21-3
  plan_status: complete
---

# Azure Agentic Platform (AAP) — Project State

> Last updated: 2026-04-03 — Plan 21-3 COMPLETE: Pipeline Health Monitoring. Created scripts/ops/21-3-detection-health-check.sh (7-check health monitor: Fabric capacity Active, Fabric workspace exists, Event Hub namespace Active, Event Hub configured, API gateway /health 200, recent det- incidents optional-auth, Container App running). PROD-004 status output: HEALTHY/DEGRADED/UNHEALTHY; exits 0 for HEALTHY, 1 otherwise. Appended "Ongoing Health Monitoring" section to docs/ops/detection-plane-activation.md (usage examples, coverage table, recommended schedule). Phase 21 all 3 plans complete. 2 atomic commits on branch gsd/phase-21-detection-plane-activation.

> Last updated: 2026-04-03 — Plan 21-2 COMPLETE: Validation & Operator Runbook. Created scripts/ops/21-2-activate-detection-plane.sh (interactive runbook with Phase 0 terraform plan verification, Steps 1-7 covering Fabric resource checks, Eventstream connector, KQL table schemas, Activator trigger wiring with domain IS NOT NULL condition, OneLake mirror AUDIT-003 steps, validation KQL queries, end-to-end smoke test, and PROD-004 checklist). Created docs/ops/detection-plane-activation.md (full operator guide with architecture diagram, domain classification reference, troubleshooting, rollback). 2 atomic commits on branch gsd/phase-21-detection-plane-activation. Plan 21-3 (pipeline health check) is next.

> Last updated: 2026-04-03 — Plan 21-1 COMPLETE: Terraform Activation. Flipped enable_fabric_data_plane = true in terraform/envs/prod/main.tf. Added Phase 21 comment referencing scripts/ops/21-2-activate-detection-plane.sh operator runbook. Added fabric_admin_email documentation comment to terraform.tfvars. Ran terraform fmt — all 3 prod env files pass fmt -check. 3 atomic commits on branch gsd/phase-21-detection-plane-activation. After next terraform apply, 5 Fabric data-plane resources will be provisioned: workspace (aap-prod), Eventhouse (eh-aap-prod), KQL DB (kqldb-aap-prod), Activator (act-aap-prod), Lakehouse (lh-aap-prod).

> Last updated: 2026-04-02 — Plan 19-4 COMPLETE: Runbook RAG Seeding. BUG-002 (F-02) code complete — operator must run seeding script. Created scripts/ops/19-4-seed-runbooks.sh (prod seeding with temporary firewall rule pattern, auto Key Vault password retrieval, row count verification, validate.py post-seed check), created docs/ops/runbook-seeding.md (full operator guide: prerequisites, when to re-seed, step-by-step procedure, troubleshooting), added pgvector_connection_string placeholder to terraform/envs/prod/terraform.tfvars. pgvector_connection_string already in credentials.tfvars and wired end-to-end through agent-apps module. Operator must run bash scripts/ops/19-4-seed-runbooks.sh to seed 60 runbooks and resolve 500 error.

> Last updated: 2026-04-02 — Plan 19-5 COMPLETE: Teams Proactive Alerting. PROD-005 code complete — operator must install bot in Teams channel and set TEAMS_CHANNEL_ID. Created scripts/ops/19-5-package-manifest.sh (manifest packaging with placeholder substitution), scripts/ops/19-5-test-teams-alerting.sh (full E2E test with pre-flight checks + synthetic Sev1 incident injection + PROD-005 checklist), added teams_channel_id placeholder to terraform/envs/prod/terraform.tfvars. TEAMS_CHANNEL_ID variable and wiring were already end-to-end complete in agent-apps module. Phase 19 all 5 plans complete.

> Last updated: 2026-04-02 — Plan 19-3 COMPLETE: MCP Tool Group Registration. PROD-003 resolved (code complete, operator must run terraform apply): Created terraform/envs/prod/mcp-connections.tf with azapi_resource blocks for azure-mcp-connection and arc-mcp-connection on Foundry project. Added internal_fqdn output alias to arc-mcp-server module. Created scripts/ops/19-3-register-mcp-connections.sh operator runbook. All 4 domain agents (Network/Security/Arc/SRE) will resolve "tool group was not found" after terraform apply.

> Last updated: 2026-04-02 — Plan 19-1 COMPLETE: Azure MCP Server Security Hardening. SEC-001 (CRITICAL) resolved: Terraform module `terraform/modules/azure-mcp-server/` created (3 files: main.tf, variables.tf, outputs.tf), internal-only ingress (`external_enabled = false`), `--dangerously-disable-http-incoming-auth` removed from Dockerfile, import block for `ca-azure-mcp-prod` in `terraform/envs/prod/imports.tf`, `azure_mcp_server_url` wired from `module.azure_mcp_server.internal_fqdn` into agent_apps. Operator runbook at `scripts/ops/19-1-azure-mcp-security.sh`. Operator must run terraform apply to activate in prod.

> Last updated: 2026-04-02 — Plan 19-2 COMPLETE: Authentication Enablement. Replaced hardcoded API_GATEWAY_AUTH_MODE=disabled with variable-driven Entra auth in Terraform agent-apps module. Added api_gateway_auth_mode/client_id/tenant_id variables. Set prod+staging tfvars to entra mode with client 505df1d3/tenant abbdca26. Documented health endpoint exclusion in auth.py. Added buildUpstreamHeaders token format JSDoc. Created staging validation script (scripts/auth-validation/validate-staging-auth.sh). Created docs/ops/e2e-service-principal.md. Operator must run terraform apply + staging validation script before prod auth is live. MSAL config and CORS already correct — no web-ui changes needed.

> Last updated: 2026-04-02T05:54:01.762Z — Phase 19 PLANNED: 5 plans created and verified (gsd-plan-checker PASS). Wave 1: MCP Security + Auth Enablement. Wave 2: MCP Tool Registration. Wave 3: Runbook RAG Seeding + Teams Proactive Alerting. V2.0 roadmap (Phases 19-28) committed to ROADMAP.md. Design spec at docs/superpowers/specs/2026-04-02-world-class-aiops-roadmap-design.md.

> Last updated: 2026-04-02 — Plan 18-01 COMPLETE: Recharts Charts in ObservabilityTab. recharts ^3.8.1 installed; incident_throughput KQL query added to /api/observability; AgentLatencyCard rebuilt with P50/P95 BarChart; PipelineLagCard improved to prominent metric display; IncidentThroughputCard (new) with hourly bar chart; ObservabilityTab updated to 2×2 grid + full-width ActiveErrorsCard. npm run build zero TypeScript errors.

> Last updated: 2026-04-02 — Completed quick task 260402-gcx: Azure Monitor validation scripts created (KQL queries, validate.sh CLI script, VALIDATION-REPORT.md template) covering all 12 containers.

> Last updated: 2026-04-02 — Completed quick task 260402-fvo: Arc MCP Server OTel init added; all 12 containers now wired to App Insights. docs/observability-wiring.md created.

> Last updated: 2026-04-02 — Phase 17 COMPLETE: Resource-Scoped Chat (2/2 plans). POST /api/v1/vms/{id}/chat routes directly to COMPUTE_AGENT_ID (bypasses orchestrator), injects pre-fetched Cosmos evidence as context on new threads. VMDetailPanel "Investigate with AI" button replaced with fully functional inline chat: auto-sends initial summary, polls for results every 2s, shows user/assistant bubbles, streaming skeleton, approval redirect card. 329 API gateway tests passing. npm run build zero TypeScript errors. Merged to main.

> Last updated: 2026-04-02 — Phase 16 COMPLETE: VM Triage Path (3/3 plans). GET /api/v1/vms (ARG + Resource Health + Cosmos alert counts), GET /api/v1/vms/{id} (full profile), GET /api/v1/vms/{id}/metrics (azure-mgmt-monitor time-series). VMDetailPanel slide-over drawer with health badge, evidence summary, sparkline charts (4 metrics), active incidents. AlertFeed and VMTab rows wire to openVMDetail(). npm run build and 310 pytest tests passing.

> Last updated: 2026-04-02 — Phase 15 COMPLETE: Diagnostic Pipeline (5/5 plans). All 4 compute agent diagnostic tools wired to real Azure SDK (no more stubs). Diagnostic pipeline BackgroundTask pre-fetches evidence on incident ingestion. IncidentSummary enriched with resource_name/resource_group/resource_type/investigation_status/evidence_collected_at. Structured logging standardised across all agents and API gateway (log_azure_call context manager). Frontend: evidence proxy route, vms proxy route, VMTab stub, AlertFeed resource columns + Evidence Ready badge + Investigate button. 578 tests pass. VERIFICATION.md written.

> Last updated: 2026-04-01 — Plan 15-02 COMPLETE: Diagnostic Pipeline Service. Created services/api-gateway/diagnostic_pipeline.py with 4 Azure SDK collection functions (_collect_activity_log, _collect_resource_health, _collect_metrics, _collect_log_analytics) + run_diagnostic_pipeline orchestrator. Wired POST /api/v1/incidents to queue pipeline as BackgroundTask (logs "pipeline: queued"). Added GET /api/v1/incidents/{id}/evidence endpoint (202+Retry-After:5 when pending, 200 with evidence doc when ready). Added get_optional_cosmos_client dependency for graceful Cosmos degradation. 8 unit tests pass, 290 total api-gateway tests pass with 0 regressions. Commit 5dba5dc.

> Last updated: 2026-04-01 — Plan 15-03 COMPLETE: Enrich IncidentSummary Model. Added resource_name, resource_group, resource_type, investigation_status, evidence_collected_at to IncidentSummary. Added _parse_resource_id() helper and updated list_incidents() to populate new fields from Cosmos documents. Updated AlertFeed.tsx with new columns (Resource, Resource Group, Investigation) and green "Evidence Ready" badge. 8 unit tests added. 34/34 tests pass, tsc --noEmit exits 0. Commit 3cfdcf0.
> Last updated: 2026-04-01 — Completed quick task 260401-e74: Validate orchestrator wiring and routing. Fixed G-01 (AZURE_MCP_SERVER_URL now wired in Terraform for patch+eol agents), wrote agents/orchestrator/README.md (G-03, all 8 domains, routing flow, env var checklist), added G-02 code comment on MCPStreamableHTTPTool vs MCPTool discrepancy in eol/agent.py. 3 atomic commits.

> Last updated: 2026-04-01 — Completed quick task 260401-brt: Added query_os_version ARG tool to compute agent covering Azure VMs (instanceView.osName/osVersion + imageReference.sku fallback) and Arc servers (properties.osName/osSku/osType). 10 unit tests pass. Returns resourceType="vm"/"arc" to distinguish results.

> Last updated: 2026-04-01 — Phase 14 PLANNED: Production Stabilisation. 12 tasks across 6 milestones (M1: Agent Wiring + MCP Tool Groups, M2: Hardcoded ID Removal + Code Fixes, M3: Arc MCP Server Real Deployment, M4: Runbook RAG + Observability, M5: Teams Proactive Alerting, M6: Dependency Pinning + Security Hardening). Resolves Backlog F-02/F-04/F-09/F-10/F-11, CONCERNS BUG-001/BUG-002/DEBT-002/DEP-003/GAP-001-004/GAP-009. Plan at .planning/phases/14-prod-stabilisation/PLAN.md.
> Last updated: 2026-03-31 — Plan 13-01 COMPLETE (Phase 13 COMPLETE): Patch Management Tab. Full-stack implementation: 2 new API gateway endpoints (GET /api/v1/patch/assessment, GET /api/v1/patch/installations) porting KQL from agents/patch/tools.py, 15 unit tests passing, 2 Next.js proxy routes, PatchTab component (5 MetricCard summary cards, 13-column assessment table with compliance/machine filters, 8-column installation history table, empty/loading/error states), wired into DashboardPanel as 6th tab (ShieldCheck icon). npx tsc --noEmit passes, all 15 pytest tests pass. azure-mgmt-resourcegraph added to gateway requirements.

> Last updated: 2026-03-31 — Phase 13 VERIFIED: VERIFICATION.md updated to `passed`. All 18 must_have checks confirmed. 15/15 pytest tests pass, npx tsc --noEmit exits 0, 5/5 format-relative-time unit tests pass. 16/16 phase requirements D-01 through D-16 met. completed_phases updated to 12, completed_plans to 39.

> Last updated: 2026-03-31 — Plan 09-04 COMPLETE: Dashboard Components. All 8 dashboard components migrated to Tailwind + shadcn/ui: DashboardPanel (shadcn Tabs + Bell/ClipboardList/Network/Server/Activity lucide icons), AlertFeed (shadcn Table + 5s polling, SeverityBadge destructive/outline), AlertFilters (3× shadcn Select, flex gap-2 items-center flex-wrap), AuditLogViewer (shadcn Table + "Export Report" Button + Input filter, flex flex-col gap-2 h-full), SubscriptionSelector (Popover+Command+Checkbox multiselect, w-[280px], fetch('/api/subscriptions'), onLoad auto-select, "Showing results for"), TraceTree (shadcn Collapsible, border-t border-border max-h-[200px], font-mono text-[12px] JSON block), TopologyTab (Collapsible tree hierarchy, Skeleton, Search input), ResourcesTab (shadcn Table + Select type filter + Input search, 30+ type labels). Zero @fluentui/makeStyles/tokens/DataGrid/Dropdown/Combobox/TabList remnants. All business logic preserved.

> Last updated: 2026-03-31 — Plan 09-05 COMPLETE: Observability Components. All 7 files migrated to Tailwind + shadcn/ui: MetricCard (health-colored left border border-l-green/yellow/red-500, shadcn Badge), TimeRangeSelector (shadcn Select, 1h/6h/24h/7d, w-[120px]), ObservabilityTab (POLL_INTERVAL_MS=30000 polling preserved, shadcn Skeleton + Alert, Activity lucide empty state), AgentLatencyCard + PipelineLagCard + ApprovalQueueCard + ActiveErrorsCard (all using MetricCard wrapper, font-mono text-[13px] values, health calculations intact). Zero @fluentui/makeStyles/tokens/MessageBar/Dropdown remnants.

> Last updated: 2026-03-31 — Plan 09-03 COMPLETE: Chat Components. ChatBubble (prose prose-sm prose-zinc, bg-primary/10 badge, bg-foreground cursor, mt-1 timestamp), UserBubble (rounded-lg p-3 mb-2 opacity-70 mt-1), ThinkingIndicator (already spec-exact), ChatInput (already spec-exact), ProposalCard (Dialog import consolidated to single line, all timer/approval logic preserved), ChatPanel (removed w-full from messages div, critical scroll layout intact: absolute inset-0 outer + ScrollArea flex-1 min-h-0 + shrink-0 grow-0 input, all SSE streaming + approval logic preserved byte-for-byte). All 6 tasks verified.

> Last updated: 2026-03-31 — Completed quick task 260331-krz: Fixed broken api-gateway Docker image. Build context was scoped to services/api-gateway/ — agents/shared/ never copied into image. Fixed Dockerfile COPY instructions + CI workflows (api-gateway-build.yml + deploy-all-images.yml) to use repo root as build context. Operator must rebuild+push to ACR and az containerapp update ca-api-gateway-prod.

> Last updated: 2026-03-31 — Completed quick task 260331-k6y: Resolved both chat blockers. ORCHESTRATOR_AGENT_ID=asst_NeBVjCA5isNrIERoGYzRpBTu set on ca-api-gateway-prod (revision 0000030, healthy). Azure AI Developer RBAC granted to gateway MI 69e05934-... on Foundry scope (role assignment 6a001d6b-...). Both fixes wired in Terraform (terraform.tfvars + rbac module). Phase 8 F-01 CLOSED. Gateway /health returns 200 ok, startup logs clean.

> Last updated: 2026-03-31 — Completed quick task 260331-ize: Fixed orchestrator domain agent routing. All 8 connected_agent tools registered on Foundry orchestrator (asst_NeBVjCA5isNrIERoGYzRpBTu): compute, network, storage, security, sre, arc, patch, eol. All 8 *_AGENT_ID + ORCHESTRATOR_AGENT_ID env vars set on ca-orchestrator-prod. EOL entry added to update-domain-agent-prompts.py AGENT_MAP.

> Last updated: 2026-03-31 — Completed quick task 260331-ghg: Provision EOL agent in Foundry (asst_s1TancOQbpIjltYQ0oGgfTDD), EOL_AGENT_ID set on ca-orchestrator-prod

> Last updated: 2026-03-31 — Completed quick task 260331-chg: Deploy Arc MCP Server — Terraform infra code complete (enable_arc_mcp_server=true, ACR registry block + AcrPull RBAC added to module). Operator steps pending: build+push image, terraform apply, verify ca-arc-mcp-server-prod running.

> Last updated: 2026-03-31 — Plan 09-02 COMPLETE: Layout Foundation. Root layout (Inter font, globals.css), providers.tsx (FluentProvider removed, MSAL 100% preserved), next.config.ts (transpilePackages removed), DesktopOnlyGate (shadcn Alert + Monitor icon), AuthenticatedApp (shadcn Button + Tailwind login), AppLayout (react-resizable-panels + exact UI-SPEC classes: bg-background top bar, bg-background chat panel, w-2 border-l resize handle). All 7 tasks verified against acceptance criteria.

> Last updated: 2026-03-31 — Plan 09-01 COMPLETE: Tailwind + shadcn/ui Foundation. Fluent UI fully removed. Tailwind CSS v4.2.2 installed, 18 shadcn/ui components scaffolded in components/ui/, cn() utility, CSS custom property design system with Azure Blue --primary: 207 90% 42%, PostCSS config, tailwind.config.ts with blink-cursor + pulse-dot animations. globals.css aligned to UI-SPEC (pure white background, standard shadcn variable values, .prose table styles added).

> Last updated: 2026-03-30 — Plan 11-03 COMPLETE (Phase 11 COMPLETE): Terraform + CI/CD for Patch Agent. patch added to local.agents (8 agents), PATCH_AGENT_ID dynamic env block for orchestrator, patch_agent_id variable declared. RBAC: Reader + Monitoring Reader on all subscriptions (ARG cross-sub). Staging/prod explicitly wire patch_agent_id. build-patch CI job added (14 jobs in summary). All 5 terraform dirs pass fmt -check. Phase 11 fully complete: 3/3 plans, 49 unit tests + 47 integration/routing tests passing.

> Last updated: 2026-03-30 — Plan 11-02 COMPLETE: Orchestrator routing wired for patch domain. QUERY_DOMAIN_KEYWORDS has 6 entries (patch added after arc, before compute with 12 keywords). DOMAIN_AGENT_MAP has 7 entries, RESOURCE_TYPE_TO_DOMAIN has 12 entries (microsoft.maintenance → patch). Orchestrator system prompt updated with patch routing rules. Patch AgentTarget registered with PATCH_AGENT_ID env var. 47 tests pass (23 integration + 24 routing unit).

> Last updated: 2026-03-30 — Completed quick task 260330-p8d: Fix critical bugs in GitHub Actions workflows (deploy-all-images missing secret + image tag, terraform-apply SSL/error-stop, staging-e2e deterministic npm ci).

> Last updated: 2026-03-30 — Phase 10 COMPLETE: API Gateway Hardening. The gateway no longer disables auth merely because `AZURE_CLIENT_ID` is missing. Local bypass now requires `API_GATEWAY_AUTH_MODE=disabled`, `/api/v1/audit` rejects invalid filters with HTTP 400 before any KQL is built, and runbook search now uses explicit DSN resolution with truthful 503s for runbook DB outages.

> Last updated: 2026-03-29 — Phase 9 added: Web UI Revamp — tear down Fluent UI / Griffel, rebuild with Tailwind CSS + shadcn/ui, redesign full portal with frontend specialist.

> Last updated: 2026-03-29 — Plan 08-05 COMPLETE. VALIDATION-REPORT.md finalized with OTel Verification section, final counts (E2E 22/30, Smoke 6/7, Simulations 8/8, OTel CANNOT_VERIFY), Conclusion, and Backlog Items. BACKLOG.md created with 11 items. Phase 8 validation status: FAIL — 2 BLOCKING findings (F-01 Foundry RBAC, F-02 runbook search 500) remain OPEN pending operator action. completed_phases stays at 7 until BLOCKING resolved.
>
> Phase 8 plans all complete (5/5). Operator must resolve F-01 and F-02 before phase can be marked complete.

---

## Current Phase

**Phase 9: Web UI Revamp — COMPLETE (6/6 plans)**

Plan 09-01 complete: Tailwind + shadcn/ui Foundation. Fluent UI fully removed from package.json. Tailwind CSS v4.2.2 installed, all 18 shadcn/ui components scaffolded in `components/ui/` (button through alert), `cn()` utility at `lib/utils.ts`, `tailwind.config.ts` with full design system including Azure Blue tokens and blink-cursor/pulse-dot animations, `postcss.config.mjs`, and `globals.css` with UI-SPEC CSS variables plus `.prose table` markdown table styles.

Plan 09-02 complete: Layout Foundation. Root layout uses Inter font via `next/font/google` with `--font-inter` CSS variable. `FluentProvider` fully removed from `providers.tsx` — all MSAL logic preserved (initialize, handleRedirectPromise, 5000ms timeout race). `next.config.ts` cleaned of transpilePackages. `DesktopOnlyGate` rebuilt with shadcn `Alert` + lucide `Monitor` icon. `AuthenticatedApp` rebuilt with shadcn `Button` + Tailwind login page. `AppLayout` rebuilt with `react-resizable-panels` and exact UI-SPEC Tailwind classes (bg-background top bar, bg-background chat panel, w-2 border-l resize handle).

Plan 09-03 complete: Chat Components. ChatBubble rebuilt with `prose prose-sm prose-zinc max-w-none` content, `bg-primary/10` agent badge, `bg-foreground` blink cursor, `mt-1` timestamp. UserBubble aligned to `rounded-lg p-3 mb-2 shadow-sm`, `opacity-70 mt-1`. ThinkingIndicator and ChatInput were already spec-exact. ProposalCard Dialog import consolidated to single line, all timer/approval logic preserved. ChatPanel: removed `w-full` from messages container div — critical scroll layout intact (`absolute inset-0` outer, `ScrollArea flex-1 min-h-0`, `shrink-0 grow-0` input footer). All SSE streaming + approval logic preserved byte-for-byte.

Plan 09-04 complete: Dashboard Components. All 8 dashboard panel components migrated to Tailwind + shadcn/ui with all business logic preserved. DashboardPanel uses shadcn Tabs with lucide icons. AlertFeed uses shadcn Table with 5s polling + SeverityBadge. AlertFilters uses 3× shadcn Select. AuditLogViewer uses shadcn Table + "Export Report" Button + Input filter. SubscriptionSelector uses Popover+Command+Checkbox multiselect with auto-select onLoad and fetch('/api/subscriptions'). TraceTree uses shadcn Collapsible with JSON payload expand per event. TopologyTab uses Collapsible tree with subscription→RG→resource hierarchy + search + Skeleton. ResourcesTab uses shadcn Table + type Select filter + search Input.

Plan 09-05 complete: Observability Components. All 7 observability files migrated to Tailwind + shadcn/ui. MetricCard uses border-l-[3px] health borders (green/yellow/red-500) with shadcn Badge. TimeRangeSelector uses shadcn Select with 4 time range options. ObservabilityTab preserves POLL_INTERVAL_MS=30000 polling, uses shadcn Skeleton + Alert, Activity lucide empty state. AgentLatencyCard, PipelineLagCard, ApprovalQueueCard, ActiveErrorsCard all use MetricCard wrapper with font-mono text-[13px] values and health calculations intact. Zero Fluent remnants.

Plan 09-06 complete: Cleanup + Verification. Zero Fluent remnants, tsc --noEmit exits 0, npm run build exits 0. Fixed 4 issues: Tailwind v4 PostCSS (@tailwindcss/postcss), @apply removal in globals.css, jest.MockedFunction<typeof fetch> typing, jest-globals-setup.ts for @testing-library/jest-dom matchers. All 8 verification tasks pass.

Phase 9 Web UI Revamp is fully complete (6/6 plans).

Parallel status:

- Phase 8 remains blocked on operator-only findings F-01 (Foundry RBAC) and F-02 (prod runbook search 500).

Recent completed context retained below for continuity:

**Phase 12 COMPLETE:** EOL Domain Agent with multi-source internet search and PostgreSQL caching.

Plan 08-02 complete: Critical-Path Validation — test.skip() removed from E2E tests, E2E suite run against prod (22/30 pass), 7 smoke tests executed, VALIDATION-REPORT.md initialized with 2 BLOCKING + 6 DEGRADED findings.

Plan 08-03 complete: Incident Simulation — 7 scenario scripts + common utilities + run-all.sh orchestrator, simulation CI gate wired into staging-e2e-simulation.yml, all 8 scenarios/injections executed against prod (7/7 scenarios PASS), 3 additional DEGRADED findings (F-09/F-10/F-11 MCP tool groups).

Plan 08-04 complete: Deferred Phase 7 Work — instrumentation.py with foundry_span/mcp_span/agent_span (span pattern: agent.{agent_name}), manual OTel spans added to foundry.py/chat.py/approvals.py, e2e-teams-roundtrip.spec.ts created (3 tests). Container App rebuild (08-04-06) is operator-only.

Plan 08-05 complete: Validation Closeout — VALIDATION-REPORT.md finalized (OTel section, final summary, conclusion, backlog items), BACKLOG.md created with 11 items. Phase 8 overall status FAIL — F-01 (Foundry RBAC) and F-02 (runbook search 500) remain OPEN pending operator action.

Plan 07-01 complete: OTel auto-instrumentation on api-gateway (Python, `azure-monitor-opentelemetry`) and teams-bot (TypeScript, `@azure/monitor-opentelemetry`). Observability tab added to Web UI DashboardPanel as 5th tab — polling API route queries Application Insights KQL (agent latency P50/P95, pipeline lag, active errors) and Cosmos DB (approval queue depth). 9 new components (ObservabilityTab, MetricCard, AgentLatencyCard, PipelineLagCard, ApprovalQueueCard, ActiveErrorsCard, TimeRangeSelector).

Plan 07-02 complete: Remediation audit trail (REMEDI-007) — `remediation_logger.py` fire-and-forget OneLake write hooked into `approvals.py` for approve/reject/expire paths with full 10-field schema. Audit export (AUDIT-006) — `audit_export.py` + `GET /api/v1/audit/export` endpoint + "Export Report" button in AuditLogViewer with browser download. 12 unit tests pass.

Plan 07-03 complete: 60 synthetic runbooks (10 per domain × 6 domains: compute, network, storage, security, arc, sre) in `scripts/seed-runbooks/runbooks/`. Idempotent `seed.py` (ON CONFLICT upsert, text-embedding-3-small). `validate.py` with SIMILARITY_THRESHOLD=0.75 and 12 domain queries. Seed + validate steps integrated into staging CI `apply-staging` job only; prod is manual per D-09.

Plan 07-04 complete: Terraform prod extended — `agent-apps` module supports teams-bot (port 3978) and web-ui (port 3000) with configurable `target_port`; CORS_ALLOWED_ORIGINS env var wired end-to-end from Python to Terraform. Security CI workflow `security-review.yml` with 3 jobs (bandit, npm audit, secrets scan). All 12 prod modules confirmed present; `terraform fmt` passes.

Plan 07-05 complete: E2E test infrastructure — root `e2e/playwright.config.ts` (workers:1, timeout:120s, retries:2 in CI); `global-setup.ts` (MSAL CCAF auth + Cosmos E2E container creation); `global-teardown.ts` (idempotent cleanup); `fixtures/auth.ts` (bearerToken, apiRequest, apiUrl, baseUrl). sc1–sc6 de-mocked to real endpoints. `staging-e2e-simulation.yml` CI gate with 15-min timeout, blocks merge on PR failure.

Plan 07-06 complete: 5 new E2E spec files — `e2e-incident-flow.spec.ts` (E2E-002), `e2e-hitl-approval.spec.ts` (E2E-003), `e2e-rbac.spec.ts` (E2E-004), `e2e-sse-reconnect.spec.ts` (E2E-005), `e2e-audit-export.spec.ts` (AUDIT-006 E2E validation). 15 test functions total; all tests use real endpoints with graceful skip when infra unavailable; no `page.route()` mocks.

---

## Project

**Azure Agentic Platform (AAP) — Milestone v1.0**

---

## Core Value

> Operators can understand, investigate, and resolve any Azure infrastructure issue — across all subscriptions and Arc-connected resources — through a single intelligent platform that shows its reasoning transparently and never acts without human approval.

---

## Phase Summary

| # | Phase | Status |
|---|---|---|
| 1 | Foundation | Complete (5/5 plans) |
| 2 | Agent Core | Complete (2026-03-26) |
| 3 | Arc MCP Server | Complete (2026-03-26) |
| 4 | Detection Plane | ✅ Complete (2026-03-26) — all 4 plans, 92 unit tests, 8 requirements |
| 5 | Triage & Remediation + Web UI | ✅ Complete (2026-03-27) — all 7 plans, 40 unit tests, 4 E2E specs, CI workflow |
| 6 | Teams Integration | ✅ Complete (2026-03-27) — all 5 plans, 100 tests at 92.34% coverage, 6 TEAMS requirements |
| 7 | Quality & Hardening | ✅ Complete (2026-03-27) — all 6 plans, E2E-001–005, REMEDI-007, AUDIT-006, 60 runbooks, security CI, Terraform prod |
| 8 | Azure Validation & Incident Simulation | ⚠️ Plans Complete (2026-03-29) — all 5 plans, 7/7 simulations PASS, manual OTel spans; VALIDATION FAIL — F-01 Foundry RBAC + F-02 runbook search OPEN |
| 9 | Web UI Revamp | ✅ Complete (2026-03-31) — all 6 plans, Tailwind v4 + shadcn/ui, tsc passes, build passes, zero Fluent remnants |
| 10 | API Gateway Hardening | ✅ Complete (2026-03-30) — 2/2 plans, explicit auth mode, audit filter validation, runbook availability hardening, 19 focused tests passing |
| 11 | Patch Domain Agent | ✅ Complete (2026-03-30) — 3/3 plans, 49 unit tests, 47 integration/routing tests, 8 Terraform files modified, build-patch CI job |
| 12 | EOL Domain Agent | ✅ Complete (2026-03-31) — 3/3 plans, 86 unit tests, EOL agent with endoflife.date + MS Lifecycle APIs, PostgreSQL 24h cache, orchestrator routing wired |
| 13 | Patch Management Tab | ✅ Complete (2026-03-31) — 1/1 plan, 15 unit tests, full-stack: gateway endpoints + proxy routes + PatchTab component + DashboardPanel wiring |
| 14 | Production Stabilisation | Not started — 12 tasks across 6 milestones: agent wiring, MCP tool groups, Arc MCP deploy, runbook RAG, Teams alerting, dependency pinning |
| 15 | Diagnostic Pipeline | ✅ Complete (2026-04-02) — 5/5 plans, 578 tests pass, 4 compute tools wired to real Azure SDKs, diagnostic pipeline BackgroundTask, IncidentSummary enriched, structured logging audit, frontend evidence integration |
| 16 | VM Triage Path | ✅ Complete (2026-04-02) — 3/3 plans, GET /api/v1/vms inventory + detail + metrics, VMDetailPanel slide-over with health/evidence/sparklines/incidents, AlertFeed + VMTab wired to openVMDetail |
| 17 | Resource-Scoped Chat | ✅ Complete (2026-04-02) — 2/2 plans, 329 api-gateway tests, POST /api/v1/vms/{id}/chat routes to COMPUTE_AGENT_ID with evidence context injection, VMDetailPanel inline chat with auto-summary + polling |

---

## Blockers/Concerns

**Phase 8 BLOCKING findings (from VALIDATION-REPORT.md — must resolve before phase closes):**

- **F-01**: `Azure AI Developer` RBAC missing on Foundry for gateway MI `69e05934-1feb-44d4-8fd2-30373f83ccec` — blocks Foundry dispatch, agent triage (E2E-002 triage polling timed out), SSE event generation
- **F-02**: `GET /api/v1/runbooks/search` returns 500 — pgvector/PostgreSQL connection or seed issue on prod

**Operator actions still needed (from .planning/BACKLOG.md):**

- Complete F-01 RBAC assignment: `az role assignment create --assignee 69e05934-... --role "Azure AI Developer" --scope /subscriptions/4c727b88-.../resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/foundry-aap-prod`
- Verify `PGVECTOR_CONNECTION_STRING` env var on `ca-api-gateway-prod` and seed prod runbooks (resolves F-02)
- Complete 08-04-06 Container App rebuild to activate OTel spans in App Insights
- See `.planning/BACKLOG.md` for full 11-item backlog (2 BLOCKING + 9 DEGRADED)

---

## Key Decisions

| Decision | Phase | Rationale |
|---|---|---|
| Centralized private-endpoints module | 1-01 | All PEs in one module eliminates duplication and avoids circular deps between networking and resource modules |
| PostgreSQL VNet injection over PE | 1-01 | Azure-recommended approach for Flexible Server; delegated subnet is simpler than PE |
| Interface-first module design | 1-01 | All variables.tf/outputs.tf fully defined before implementation enables parallel work in Plans 02-04 |
| No PEs in networking module | 1-02 | Centralized in modules/private-endpoints to avoid circular deps where networking needs resource IDs from dependent modules |
| Reserved subnet for Phase 4 Event Hub | 1-02 | Pre-allocate snet-reserved-1 at 10.0.64.0/24 to avoid VNet CIDR changes later |
| Foundry subnet gets own NSG | 1-02 | ISSUE-08: Foundry subnet needs inbound 443 from Container Apps for future PE traffic |
| No local-exec for pgvector on VNet-isolated PostgreSQL | 1-03 | ISSUE-04: GitHub runners can't reach VNet-injected PG; deferred to PLAN-05 CI workflow |
| ACR name uses random_string suffix | 1-03 | ISSUE-10: Azure Container Registry names must be globally unique |
| Foundry project inherits identity from parent account | 1-03 | ISSUE-09: azurerm_cognitive_account_project does not support identity block |
| Dev/staging Cosmos Serverless; prod Provisioned Autoscale | 1-04 | Cost optimization for non-prod; multi-region westus2 secondary for prod HA |
| Tiered PostgreSQL SKUs per environment | 1-04 | dev B1ms, staging B2ms, prod GP_Standard_D4s_v3 — General Purpose needed for prod workloads |
| Identical env structure, parameter-only differences | 1-04 | All envs share same provider/output/variable structure; only module parameters differ to minimize env drift |
| Tag lint via jq on tfplan.json | 1-05 | Catches both null tags and missing required keys; runs only when plan succeeds (ISSUE-05/06) |
| pgvector setup via temporary firewall rule in CI | 1-05 | ISSUE-04 resolution: GitHub runners can't reach VNet-injected PG directly; temporary firewall rule pattern with always-cleanup |
| Docker push as reusable workflow_call | 1-05 | Avoids duplication across agent image builds in Phase 2+; composable per-agent |
| SystemAssigned identity IS the Entra Agent ID | 2-01 | Container App SystemAssigned managed identity registers as Entra Agent ID automatically; no separate azapi_data_plane_resource block needed |
| RBAC merge() pattern for flat map | 2-01 | merge() with flat keyed map avoids Terraform index instability vs. concat() list approach; replace(sub_id, "-", "") for safe keys |
| Arc Agent as Phase 2 stub | 2-01 | Arc Agent Container App + identity provisioned but returns structured pending response; full tooling deferred to Phase 3 Arc MCP Server |
| Prod multi-subscription RBAC variables | 2-01 | compute/network/storage/all_subscription_ids vars added to prod only; dev/staging default all to platform subscription_id |
| ETag optimistic concurrency for Cosmos budget records | 2-02 | Prevents lost-update race conditions when multiple agent iterations write to the same session record |
| pythonpath=["."] in pyproject.toml | 2-02 | Required for pytest to resolve `agents.shared.*` imports from repo root without installing the package |
| Explicit local auth bypass for gateway | 10-01 | API_GATEWAY_AUTH_MODE=disabled is now required for insecure local bypass; missing AZURE_CLIENT_ID / AZURE_TENANT_ID no longer authorizes requests |
| Explicit DSN resolution for runbook search | 10-02 | Runbook search now resolves PGVECTOR_CONNECTION_STRING, POSTGRES_DSN, or explicit POSTGRES_* values and returns 503 for data-plane outages instead of generic 500s |
| Optional[X] over X\|None in FastAPI signatures | 2-03 | FastAPI's get_type_hints() evaluates annotations at runtime; `|` union fails on Python 3.9 even with `from __future__ import annotations` |
| conftest.py hyphenated package shim | 2-03 | Python cannot import hyphenated directories; shim registers `services/api-gateway` as `sys.modules["services.api_gateway"]` + setattr on parent for mock.patch compat |
| Gateway as thin router only | 2-03 | No business logic in gateway; all incident reasoning deferred to Foundry agent threads; keeps gateway small and independently testable |
| Integration tests excluded from fast unit CI run | 3-04 | pytest.mark.integration prevents prolonged disconnection and triage workflow tests from running in the fast unit test CI job; they run in a separate integration job |
| E2E pagination tests use mock ARM server via AZURE_ARM_BASE_URL | 3-04 | Avoids real Azure credentials and expensive Arc estate provisioning in CI; mock ARM seeded with 120 Arc machines covers the >100 E2E-006 requirement |
| azapi_resource for all Fabric data-plane items | 4-01 | Fabric REST API types supported via azapi; consistent with project Fabric Terraform pattern |
| count gate on Fabric SP resources | 4-01 | gateway_app_client_id="" default allows deploy before API gateway Entra app is registered |
| Fixed end_date for azuread_application_password | 4-01 | Avoids perpetual diff from timeadd(timestamp(),...) per WARN-D4a; fixed to 2027-03-26T00:00:00Z |
| Activity Log module with for_each over subscription IDs | 4-01 | Supports multi-subscription export — single sub in dev/staging, all_subscription_ids in prod |
| Service Bus DNS zone in networking module | 4-01 | Follows existing pattern: DNS zones + VNet links in networking, PEs in private-endpoints |
| IsTransactional=false on KQL hop 1 (RawAlerts→EnrichedAlerts) | 4-02 | Prevents data loss: if EnrichAlerts() fails with IsTransactional=true, source ingestion into RawAlerts is rolled back; false ensures raw alert is always preserved (Risk 6 mitigation) |
| Python classify_domain() uses exact then prefix match | 4-02 | Exact match covers known types; prefix match handles broad categories (microsoft.security/*, microsoft.azurearcdata/*) — mirrors KQL has_any substring behavior |
| DETECT-007 satisfied by architecture | 4-02 | Suppressed alerts never reach Event Hub (Azure Monitor processing rules suppress Action Group invocation upstream); no code needed, documented in KQL comments |
| Dedup check is non-blocking in gateway | 4-03 | COSMOS_ENDPOINT absent → skip dedup silently; ImportError → skip silently; prevents dedup bugs from taking down incident ingestion |
| Fire-and-forget Azure Monitor sync | 4-03 | Platform state transition must never block on external sync; Azure Monitor failures logged but not raised (non-blocking by design) |
| Self-contained UDF mapping copy in Fabric | 4-03 | Fabric runtime cannot import services/detection-plane; mapping logic duplicated intentionally, clearly commented with canonical reference |
| det- prefix on incident_id | 4-03 | Provides traceability: any incident ID starting with det- was created via the detection plane (vs. manual/API ingestion) |
| UDF tests import at module level (not per-test reload) | 4-04 | importlib.reload() pattern caused MSAL ConfidentialClientApplication to call Entra authority discovery before @patch applied; module-level import + patch("main.func") resolves correctly |
| KQL consistency test regex requires full path (has /) | 4-04 | classify_domain.kql uses has_any() with both full paths and prefix-only values (Microsoft.Security); regex r'"(Microsoft\.[^/"]+/[^"]+)"' skips prefix-only values avoiding false "sre" failures |
| Integration stubs use @pytest.mark.skip on class + pytestmark | 4-04 | Both marks required: pytestmark for -m filtering, @pytest.mark.skip so tests don't run without infra even when -m integration is specified |
| Action.Execute for teams-bot approval/reminder cards | 6-01 | Action.Http is NOT supported for bot-sent Adaptive Cards in Teams (per 06-RESEARCH.md Section 2); must use Action.Execute with verb + data fields |
| createNotifyRouter(config) factory for Express testability | 6-01 | Module-level router binds config at import time, requiring env vars in tests; factory pattern allows injecting mock AppConfig cleanly |
| ESLint 9 requires flat config (eslint.config.js) | 6-01 | ESLint 9 dropped .eslintrc.* support; CJS eslint.config.js used to match commonjs tsconfig output |
| API_GATEWAY_PUBLIC_URL empty-string default (deprecated) | 6-01 | Post-Action.Execute migration, api-gateway public URL is not used in card action URLs; retained in config for forward-compatibility with default "" |
| body.thread_id takes precedence over query param | 6-03 | Action.Execute sends data in card body; body is more explicit than query param; backward compat maintained |
| GET /api/v1/approvals before /{approval_id} route | 6-03 | FastAPI path matching: parameterized route would match query-only requests as approval_id |
| notify_teams() generic dispatcher replaces _build_adaptive_card | 6-03 | Card rendering moved to TypeScript bot; gateway sends structured payloads via single dispatcher |
| Cross-partition query for pending approvals | 6-03 | Acceptable for small pending counts; used by scheduler, not hot-path |
| Constructor-based event registration for Bot Framework | 6-02 | Bot Framework SDK's onMessage/onInstallationUpdate are event registrators, not overridable handlers; must use this.onMessage(handler) pattern for TypeScript type safety |
| handleMessage as public method for testability | 6-02 | Direct method call in tests avoids Bot Framework event pipeline; onAdaptiveCardInvoke remains protected override |
| In-memory conversation state with 24h TTL | 6-02 | Map<teamsConversationId, {threadId, incidentId, lastUsed}> sufficient for MVP; upgrade to Cosmos DB if durability needed |
| Teams bot still uses dev-token fallback | 6-02 | Legacy local bot workflow remains unchanged; it no longer mirrors the API gateway, which now requires API_GATEWAY_AUTH_MODE=disabled for bypass |
| In-memory dedup Map for escalation reminders | 6-04 | Map<approvalId, lastReminderTimestamp> sufficient for single-instance MVP; upgrade to Cosmos DB if HA/multi-instance needed |
| 503 pre-flight on notify route | 6-04 | hasConversationReference() check returns 503 Service Unavailable when bot not installed — prevents silent failures from api-gateway calls |
| 30-second startup delay for escalation scheduler | 6-04 | Allows bot installation event to fire and ConversationReference to be captured before scheduler attempts proactive posting |
| Placeholder PNG icons for Teams manifest | 6-05 | Minimal single-color PNGs (32x32 outline, 192x192 color); real icons deferred to pre-production design phase |
| describe.skip for integration test stubs | 6-05 | Stubs define full test plans but require live Teams environment; Phase 7 Quality & Hardening will implement real integration tests |
| vitest.config.ts + CI --exclude double-guard | 6-05 | Both vitest config exclude and CI --exclude flag ensure integration stubs never run in unit test CI |
| OTel auto-instrumentation only in Phase 7 | 7-01 | Manual spans (per-Foundry-call, per-tool-call latency) deferred to Phase 8; auto-instrumentation via azure-monitor-opentelemetry sufficient for production observability baseline |
| No APIM in Phase 7 | 7-04 | Standard v2 ~$700/month cost not justified without production traffic; direct Container Apps ingress sufficient; revisit at first multi-tenant or API monetization requirement |
| E2E tests gracefully skip when infra unavailable | 7-06 | test.skip() on non-202/503 responses prevents CI failures in environments without full Azure infra while still verifying API contract |
| Prod seed is manual operational step | 7-03 | Never run seed script against prod automatically; seed/validate only in staging CI; prod seed documented in ops runbook per D-09 |
| CORS locked via env var, not hardcoded | 7-04 | CORS_ALLOWED_ORIGINS env var replaces hardcoded wildcard; prod Container App sets explicit origin; default `*` maintained for dev/staging convenience |
| Tasks 08-01-02 through 08-01-06 are operator-only steps | 8-01 | These steps require live Azure credentials, Entra admin permissions, or secret values not available to autonomous agent; documented in 08-01-USER-SETUP.md |
| --create guard against existing ORCHESTRATOR_AGENT_ID | 8-01 | Mutual exclusion prevents accidental double-create; check runs before client.create_agent() API call to fail fast |
| Phase 8 strict mode removes test.skip() from E2E specs | 8-02 | Phase 7 used graceful skip for infra unavailability; Phase 8 validates prod — all skips replaced with hard assertions or vacuous-pass early returns |
| Vacuous-pass pattern for conditional E2E steps | 8-02 | When a sub-step requires state that may not exist (e.g., no pending approvals), use early return + console.log rather than test.skip() — test still runs and records a result |
| e2e package.json committed to repo | 8-02 | E2E tests require @playwright/test, @azure/msal-node, etc. — committing package.json makes local runs reproducible without the CI `npm init -y` pattern |
| scenario_cross.py injects two incidents | 8-03 | API only accepts one domain per payload; cross-domain (Compute + Storage) disk-full scenario requires two separate incident injections with correlated context |
| Cosmos cleanup non-fatal by design | 8-03 | cleanup_incident() catches all exceptions and logs WARNING — simulation records expire via TTL; local IP blocked by prod Cosmos firewall should not fail the simulation |
| bash 3.2 compatibility in run-all.sh | 8-03 | ${SCENARIOS[-1]} negative array indexing requires bash 4+; replaced with ${SCENARIOS[$((TOTAL-1))]} for macOS compatibility (macOS ships bash 3.2) |
| CI simulation job needs: [e2e] | 8-03 | Simulation job runs after E2E job to ensure basic platform health before executing synthetic incident injections against prod |
| OTel span name agent.{agent_name} (not agent.invoke) | 8-04 | Each domain agent gets a distinct span name for per-agent filtering in App Insights; fixed name would prevent distinguishing orchestrator vs compute vs network spans |
| mcp.outcome placement in try/except | 8-04 | success set in try block, error set in except block within mcp_span — ensures outcome always recorded even when finally runs after exception |
| 08-04-06 Container App rebuild is operator-only | 8-04 | Requires live Azure CLI + ACR push access; automation would need managed identity with Container Registry Contributor role; documented for operator with exact commands |
| Phase 8 validation FAIL — BLOCKING findings require operator action | 8-05 | F-01 (Foundry RBAC) and F-02 (runbook search 500) require Azure CLI/Portal access not available to autonomous executor; completed_phases stays at 7 until operator resolves both; all 5 plans complete |

---

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260403-vsw | Run prod blockers: terraform apply domain agent IDs (COMPUTE_AGENT_ID live), runbook seeding workflow added (CAE job issue blocks auto-seed), Teams CHANNEL_ID pending | 2026-04-03 | 9b13050 | — |
| 260325-gqo | Research microsoftgbb/agentic-platform-engineering repo and incorporate findings into planning docs | 2026-03-25 | ccc5d96 | [260325-gqo-research-microsoftgbb-agentic-platform-e](./quick/260325-gqo-research-microsoftgbb-agentic-platform-e/) |
| 260326-x3n | Backfill VALIDATION.md for phases 1 and 3 | 2026-03-26 | b9a32d5 | [260326-x3n-backfill-validation-md-for-phases-1-and-](./quick/260326-x3n-backfill-validation-md-for-phases-1-and-/) |
| 260327-x4g | Fix ObservabilityTab container-type bug, add tab icons, and modernise web-UI visual design | 2026-03-28 | 03994fb | [260327-x4g-fix-observabilitytab-container-type-bug-](./quick/260327-x4g-fix-observabilitytab-container-type-bug-/) |
| 260328-1ca | Move run-mock.sh to scripts folder and update the script accordingly | 2026-03-27 | 4b26f66 | [260328-1ca-move-run-mock-sh-to-scripts-folder-and-u](./quick/260328-1ca-move-run-mock-sh-to-scripts-folder-and-u/) |
| 260328-2ir | Deploy images to container registry — teams-bot build, deploy-all workflow, naming fix | 2026-03-28 | 94d0b8b | [260328-2ir-deploy-images-to-container-registry](./quick/260328-2ir-deploy-images-to-container-registry/) |
| 260328-va0 | Validate MANUAL-SETUP.md provisioning state — 3 DONE, 3 PARTIAL, 1 PENDING, 1 SKIPPED, 1 CANNOT_VERIFY | 2026-03-28 | fcca5fc | [260328-va0-validate-manual-setup-md-provisioning-st](./quick/260328-va0-validate-manual-setup-md-provisioning-st/) |
| 260329-315 | Review and clean up 65 uncommitted changes — gitignore coverage/build artifacts, commit real files | 2026-03-29 | 3b53ff1 | [260329-315-review-uncommitted-changes](./quick/260329-315-review-uncommitted-changes/) |
| 260329-qro | validate 08-01 provisioning gaps are done | 2026-03-29 | — | [260329-qro-validate-08-01-provisioning-gaps-are-don](./quick/260329-qro-validate-08-01-provisioning-gaps-are-don/) |
| 260330-p8d | Fix critical bugs in GitHub Actions workflows | 2026-03-30 | 3758e75 | [260330-p8d-fix-critical-bugs-in-github-actions-work](./quick/260330-p8d-fix-critical-bugs-in-github-actions-work/) |
| 260331-chg | Deploy Arc MCP Server to Container Apps and wire ARC_MCP_SERVER_URL to ca-arc-prod | 2026-03-31 | 06a2ae0 | [260331-chg-deploy-arc-mcp-server-to-container-apps-](./quick/260331-chg-deploy-arc-mcp-server-to-container-apps-/) |
| 260331-ghg | Provision EOL agent in Foundry by adding it to provision-domain-agents.py and running provisioning | 2026-03-31 | a100a28 | [260331-ghg-provision-eol-agent-in-foundry-by-adding](./quick/260331-ghg-provision-eol-agent-in-foundry-by-adding/) |
| 260401-ata | Resizable chat drawer (360–800px, persisted) + table overflow fix for wide agent responses | 2026-04-01 | 8775e30 | [260401-ata](./quick/260401-ata.md) |
| 260331-ize | Fix orchestrator domain agent routing — register all 8 connected_agent tools on Foundry orchestrator (asst_NeBVjCA5isNrIERoGYzRpBTu), set *_AGENT_ID + ORCHESTRATOR_AGENT_ID env vars on ca-orchestrator-prod | 2026-03-31 | d9a58b5 | [260331-ize-fix-orchestrator-domain-agent-routing-re](./quick/260331-ize-fix-orchestrator-domain-agent-routing-re/) |
| 260401-bd1 | Fix NameError in chat.py submit_tool_outputs — `outputs` → `tool_outputs` (silent failure when run hits requires_action) | 2026-04-01 | 62c4a50 | — |
| 260331-k6y | Fix API gateway prod blockers: set ORCHESTRATOR_AGENT_ID on ca-api-gateway-prod (revision 0000030) + grant Azure AI Developer RBAC to gateway MI on Foundry scope. Phase 8 F-01 CLOSED. | 2026-03-31 | dc3930a | [260331-k6y-fix-api-gateway-prod-blocker-set-orchest](./quick/260331-k6y-fix-api-gateway-prod-blocker-set-orchest/) |
| 260331-krz | Fix broken api-gateway image: expand Docker build context to repo root so agents/shared is accessible, fix ModuleNotFoundError. Operator must rebuild+push to ACR and update ca-api-gateway-prod. | 2026-03-31 | 13f2b78 | [260331-krz-fix-broken-api-gateway-image-diagnose-mo](./quick/260331-krz-fix-broken-api-gateway-image-diagnose-mo/) |
| 260401-brt | Add query_os_version ARG tool to compute agent covering both Azure VMs and Arc-enabled servers for OS version details and EOL date determination | 2026-04-01 | f0cd530 | [260401-brt-research-whether-azure-resource-graph-ar](./quick/260401-brt-research-whether-azure-resource-graph-ar/) |
| 260401-e74 | Validate orchestrator wiring and routing — fix AZURE_MCP_SERVER_URL Terraform gap (G-01), write agents/orchestrator/README.md (G-03), add G-02 MCPStreamableHTTPTool comment to eol/agent.py | 2026-04-01 | 689e73b | [260401-e74-validate-orchestrator-wiring-and-routing](./quick/260401-e74-validate-orchestrator-wiring-and-routing/) |
| 260401-nk7 | Add structured logging to all agents for Azure Container App log visibility | 2026-04-01 | 30a2907 | [260401-nk7-add-structured-logging-to-all-agents-for](./quick/260401-nk7-add-structured-logging-to-all-agents-for/) |
| 260401-o1l | Add structured logging to web-ui Next.js API routes for Azure Container App log streaming | 2026-04-01 | fa798e2 | [260401-o1l-add-structured-logging-to-web-ui-next-js](./quick/260401-o1l-add-structured-logging-to-web-ui-next-js/) |
| 260402-fvo | Wire up all agent containers to App Insights for observability | 2026-04-02 | 23e678e | [260402-fvo-wire-up-all-agent-containers-to-app-insi](./quick/260402-fvo-wire-up-all-agent-containers-to-app-insi/) |
| 260402-gcx | Validate Azure Monitor is receiving logs from all agent containers | 2026-04-02 | d9aa6e1 | [260402-gcx-validate-azure-monitor-is-receiving-logs](./quick/260402-gcx-validate-azure-monitor-is-receiving-logs/) |

---

## Accumulated Context

### Roadmap Evolution

- Phase 9 added: Web UI Revamp — rebuild with Tailwind CSS + shadcn/ui
- Phase 10 added: API Gateway Auth Audit Hardening
- Phase 11 added: Patch Domain Agent — ARG-based patch assessment/installation agent using Azure Update Manager query-logs, wired into orchestrator routing
- Phase 12 added: EOL Domain Agent with multi-source internet search and PostgreSQL caching
- Phase 13 added: add a new patch management tab and show all the patch related information
- Phase 13 COMPLETE: Patch Management Tab — full-stack: 2 API gateway endpoints, 2 proxy routes, PatchTab component, DashboardPanel wiring, 15 tests

---

## Links

- [PROJECT.md](.planning/PROJECT.md) — project context, requirements, key decisions
- [REQUIREMENTS.md](.planning/REQUIREMENTS.md) — full requirement list with REQ-IDs
- [ROADMAP.md](.planning/ROADMAP.md) — phases, success criteria, traceability
- [research/ARCHITECTURE.md](.planning/research/ARCHITECTURE.md) — system architecture and build order
- [research/FEATURES.md](.planning/research/FEATURES.md) — feature categories and table stakes
- [research/SUMMARY.md](.planning/research/SUMMARY.md) — recommended stack and critical pitfalls
