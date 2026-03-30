# Phase 12: EOL Domain Agent - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Build an `eol-agent` domain specialist that detects End-of-Life (EOL) status for software running
across Azure VMs and Arc-enabled servers. The agent queries two external sources (endoflife.date API
and Microsoft Product Lifecycle API) with source routing by product type, caches results in a new
PostgreSQL table (24h TTL, synchronous refresh on cache miss), and operates in two modes:

1. **Reactive triage** — handed off by the Orchestrator when an EOL-related incident is detected
2. **Proactive scan** — scans the full estate on demand (Fabric Activator timer or direct invocation)
   and creates incidents for resources at 90/60/30 day EOL thresholds

Software scope: OS versions (Windows Server, Ubuntu LTS, RHEL), language runtimes (.NET, Python,
Node.js), databases (SQL Server, PostgreSQL, MySQL), and Kubernetes node pool versions.

Agent follows the established domain agent pattern: spec-first, `@ai_function` tools, explicit MCP
allowlist, `ChatAgent`, Dockerfile, Terraform managed identity + RBAC.

</domain>

<decisions>
## Implementation Decisions

### EOL Data Sources

- **D-01:** The agent queries **two external sources**: `endoflife.date` REST API and the
  **Microsoft Product Lifecycle API** (`learn.microsoft.com/lifecycle`).
- **D-02:** **Source routing by product type** — MS Lifecycle API for Microsoft products
  (Windows Server, SQL Server, .NET, Azure services, IIS, Exchange); endoflife.date for everything
  else (Ubuntu, RHEL, Python, Node.js, PostgreSQL, MySQL, Kubernetes). If MS API has no data for
  a Microsoft product, fall through to endoflife.date silently.
- **D-03:** Each source gets its own `@ai_function` wrapper: `query_endoflife_date(product, version)`
  and `query_ms_lifecycle(product, version)`. Agent logic routes based on product type.
- **D-04:** No NVD/CVE cross-reference in this phase — CVE enrichment is already handled by
  the patch agent. EOL agent focuses on lifecycle dates and upgrade paths only.

### Software Scope

- **D-05:** Agent tracks EOL status for: **OS** (Windows Server 2012/2016/2019/2022/2025,
  Ubuntu LTS 18.04/20.04/22.04/24.04, RHEL 7/8/9), **runtimes** (.NET 6/7/8/9, Python 3.8–3.13,
  Node.js 16/18/20/22), **databases** (SQL Server 2016–2022, PostgreSQL 12–17, MySQL 5.7/8.x),
  **Kubernetes node pool versions** (AKS-supported K8s versions).
- **D-06:** **Inventory discovery** uses the same pattern as the patch agent: ARG
  (`patchassessmentresources`, `configurationchange`) + Log Analytics `ConfigurationData` table.
  ARG provides OS version per VM/Arc server; ConfigurationData provides installed software
  inventory (runtimes, databases) for machines with AMA agent reporting.
- **D-07:** Arc-enabled Kubernetes: agent queries `Microsoft.Kubernetes/connectedClusters` ARG
  to discover Kubernetes version on Arc K8s clusters.

### Cache Design

- **D-08:** New PostgreSQL table: `eol_cache` — flat schema:
  ```sql
  CREATE TABLE eol_cache (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product     TEXT NOT NULL,      -- e.g., "windows-server"
    version     TEXT NOT NULL,      -- e.g., "2016"
    eol_date    DATE,               -- NULL if no fixed EOL date (e.g., "rolling release")
    is_eol      BOOLEAN NOT NULL,
    source      TEXT NOT NULL,      -- "endoflife.date" | "ms-lifecycle"
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (product, version, source)
  );
  ```
- **D-09:** TTL = **24 hours**. `expires_at = cached_at + INTERVAL '24 hours'`.
- **D-10:** Cache miss / TTL expired behavior: **synchronous refresh** — query upstream before
  responding. Cache hit serves instantly; cache miss queries upstream, stores result, returns.
  No stale-serve, no background threads.
- **D-11:** The `eol_cache` table lives in the **same PostgreSQL Flexible Server** already used
  by the API gateway for runbooks. A new migration script (`003_create_eol_cache_table.sql`)
  creates it. The agent connects using the same `PG_*` environment variables pattern.
- **D-12:** Cache lookup is a helper in `agents/eol/tools.py`: `get_cached_eol(product, version)`
  returns the cached record or None if expired/missing. `set_cached_eol(...)` stores the result.

### Alerting / Proactive Scan

- **D-13:** The agent operates in **two modes**:
  1. **Reactive triage** — standard incident handoff from orchestrator. Agent investigates
     the affected resources' EOL status and produces a triage report.
  2. **Proactive scan** — a dedicated `@ai_function` tool `scan_estate_eol()` that scans
     the entire managed estate (ARG + ConfigurationData across all subscriptions) for EOL
     software, then creates incident records via the API gateway for any findings.
- **D-14:** **Alert thresholds**: 90/60/30 days before EOL. Proactive scan creates one incident
  per threshold crossing per resource (idempotent — no duplicate incidents if scan runs daily).
- **D-15:** The proactive scan is intended to be invoked periodically (daily via Fabric Activator
  timer or Azure Logic App timer trigger). The trigger setup is **infrastructure config**
  at Claude's discretion (Terraform or Fabric Activator rule).

### Remediation Posture

- **D-16:** Agent **proposes upgrade plans** — does NOT execute. Consistent with REMEDI-001.
- **D-17:** Single remediation action type: `action_type="plan_software_upgrade"` with:
  - `product`: the EOL product name + version
  - `target_version`: recommended upgrade target version (from endoflife.date `latest` field or
    MS Lifecycle recommended upgrade path)
  - `upgrade_doc_url`: link to vendor upgrade guide
  - `reversible: false` (upgrades are not trivially reversible)
- **D-18:** **Risk levels by EOL status**:
  - `already_eol` (eol_date < today) → `risk_level: "high"`
  - `within_90_days` (eol_date within 90 days) → `risk_level: "medium"`
  - `within_60_days` → `risk_level: "medium"`
  - `within_30_days` → `risk_level: "high"` (same urgency as already-EOL approaching fast)
- **D-19:** Human approval always required per REMEDI-001 — same `approval_manager` pattern
  as all other domain agents.

### Agent Structure

- **D-20:** Agent lives at `agents/eol/` following the standard layout: `agent.py`, `tools.py`,
  `__init__.py`, `Dockerfile`, `requirements.txt`.
- **D-21:** Spec file required at `docs/agents/eol-agent.spec.md` before any implementation code
  (Phase 2 spec-gate, D-01/D-03/D-04 from Phase 2 context).
- **D-22:** Shared utilities from `agents/shared/` apply as-is: `auth.get_foundry_client`,
  `otel.setup_telemetry`, `envelope.IncidentMessage`, `approval_manager`, `runbook_tool`.
- **D-23:** New HTTP client dependency for external API calls: `httpx` (async-compatible,
  already likely in base image — check `agents/requirements-base.txt`; add if missing).
- **D-24:** Orchestrator routing keywords added to `QUERY_DOMAIN_KEYWORDS` under `"eol"` entry
  (exact list at Claude's discretion — should include: `"end of life"`, `"eol"`, `"end-of-life"`,
  `"outdated software"`, `"software lifecycle"`, `"unsupported version"`, `"lifecycle status"`,
  `"deprecated version"`).
- **D-25:** `RESOURCE_TYPE_TO_DOMAIN` gets `"microsoft.lifecycle": "eol"`.
- **D-26:** `DOMAIN_AGENT_MAP` gets `"eol": "eol-agent"`.
- **D-27:** Mandatory triage workflow steps (reactive mode):
  1. Activity Log first (TRIAGE-003) — 2h look-back on affected resources.
  2. ARG inventory query — OS version per VM/Arc server across all subscriptions.
  3. ConfigurationData query — installed runtimes/databases per machine (AMA-reporting).
  4. Arc K8s query — Kubernetes version on Arc connected clusters.
  5. Cache lookup + upstream fetch for each product/version combo discovered.
  6. Classify each finding by EOL status (already_eol / within_30/60/90 / not_eol).
  7. Runbook citation (TRIAGE-005): `search_runbooks(query=..., domain="eol", limit=3)`.
  8. Diagnosis with confidence score (TRIAGE-004).
  9. Propose upgrade plans for any already-EOL or within-90-day findings (REMEDI-001).

### Claude's Discretion

- Exact KQL for ARG inventory queries (OS version extraction, ConfigurationData filtering)
- HTTP client retry/timeout strategy for external API calls (httpx timeout, max retries)
- Product slug normalization (mapping ARG OS name → endoflife.date product slug)
- MS Lifecycle API exact endpoint and authentication (likely public, no auth — confirm in research)
- Proactive scan trigger infrastructure (Fabric Activator rule or Logic App timer)
- Incident dedup logic for proactive scan (check for existing open EOL incident before creating)
- Agent system prompt text beyond what the spec and workflow above defines
- Test fixture design for endoflife.date and MS Lifecycle API mocks
- Terraform RBAC role (likely `Reader` on all subscriptions + Log Analytics Reader)
- `EOL_AGENT_ID` env var name for the Container App environment variable
- Index on `eol_cache(product, version, expires_at)` for fast lookup

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Domain Agent Pattern (replicate this structure)
- `agents/patch/agent.py` — most recent domain agent; direct template for eol-agent structure,
  ChatAgent setup, system prompt pattern, `@ai_function` tool registration, mandatory triage workflow
- `agents/patch/tools.py` — `ALLOWED_MCP_TOOLS` list, `@ai_function` decorator pattern,
  `instrument_tool_call`, `get_agent_identity` usage, asyncpg pattern for PostgreSQL queries
- `agents/patch/Dockerfile` — `FROM ${BASE_IMAGE}`, `COPY requirements.txt`, entry point pattern
- `agents/arc/agent.py` — pattern for mounting both `@ai_function` tools AND Azure MCP Server
  tools (`MCPTool`) in the same agent

### Orchestrator Routing (files to modify)
- `agents/orchestrator/agent.py` — `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, orchestrator
  system prompt routing rules, `AgentTarget` list
- `agents/shared/routing.py` — `QUERY_DOMAIN_KEYWORDS` tuple — add `"eol"` entry

### PostgreSQL Cache Pattern (existing pattern to extend)
- `services/api-gateway/migrations/001_create_runbooks_table.sql` — migration pattern to follow
  for `003_create_eol_cache_table.sql`
- `services/api-gateway/runbook_rag.py` — asyncpg connection pattern, `resolve_postgres_dsn()`,
  startup migration runner pattern

### Shared Utilities (use without modification)
- `agents/shared/envelope.py` — `IncidentMessage` TypedDict, `VALID_MESSAGE_TYPES`
- `agents/shared/auth.py` — `get_foundry_client`, `get_agent_identity`, `get_credential`
- `agents/shared/otel.py` — `setup_telemetry`, `instrument_tool_call`
- `agents/shared/approval_manager.py` — approval request pattern for REMEDI-001
- `agents/shared/runbook_tool.py` — `retrieve_runbooks` for TRIAGE-005 runbook citation

### Spec Format Reference
- `docs/agents/patch-agent.spec.md` — most recent spec; use as format template for eol-agent spec

### External API References
- `https://endoflife.date/docs` — endoflife.date API documentation (product slugs, `/api/{product}.json`, `/api/{product}/{version}.json`)
- `https://learn.microsoft.com/en-us/lifecycle/products` — Microsoft Product Lifecycle browse
- `https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata` — ConfigurationData LAW table schema for software inventory (same as patch agent D-08 reference)

### Phase Context
- `CLAUDE.md` §"Core Agent Framework" — `ChatAgent`, `@ai_function`, `AzureAIAgentClient` APIs
- `CLAUDE.md` §"Azure Integration Layer" — `azure-ai-projects` 2.0.1
- `CLAUDE.md` §"Azure MCP Server (GA)" — `monitor.query_logs`, `monitor.query_metrics` tool names
- `.planning/phases/02-agent-core/02-CONTEXT.md` — spec-gate (D-01 to D-04), agent layout
  (D-05 to D-08), managed identity per agent (D-13), RBAC via Terraform (D-14/D-15)
- `.planning/phases/11-patch-domain-agent/11-CONTEXT.md` — D-07 (ARG SDK pattern),
  D-08 (ConfigurationData queries), D-09 (merge by machine key), D-21 through D-24
  (agent structure decisions that apply identically to eol-agent)
- `.planning/REQUIREMENTS.md` §TRIAGE — TRIAGE-001 through TRIAGE-005
- `.planning/REQUIREMENTS.md` §REMEDI — REMEDI-001 (no execution without human approval)
- `.planning/REQUIREMENTS.md` §AUDIT — AUDIT-001 (preserve correlation_id), AUDIT-005 (agent attribution)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/shared/auth.py` — `get_foundry_client()`, `get_agent_identity()`, `get_credential()` — use directly
- `agents/shared/otel.py` — `setup_telemetry("aiops-eol-agent")` and `instrument_tool_call` — use directly
- `agents/shared/envelope.py` — `IncidentMessage` TypedDict — use for all inter-agent messages
- `agents/shared/approval_manager.py` — approval request submission for REMEDI-001
- `agents/shared/runbook_tool.py` — `retrieve_runbooks(query, domain="eol", limit=3)` (TRIAGE-005)
- `agents/Dockerfile.base` — base image; eol agent's Dockerfile starts `FROM ${BASE_IMAGE:-aap-agents-base:latest}`
- `services/api-gateway/runbook_rag.py` — `resolve_postgres_dsn()` helper and asyncpg pattern
  to replicate in `agents/eol/tools.py` for cache reads/writes

### Established Patterns
- `@ai_function` decorator: import from `agent_framework`, typed args, returns `Dict[str, Any]`,
  uses `instrument_tool_call` for OTel spans
- `ALLOWED_MCP_TOOLS: List[str]` — module-level explicit list, passed to `ChatAgent` constructor
- System prompt: Scope → Mandatory Triage Workflow (numbered steps) → Safety Constraints
- Agent entry point: `CMD ["python", "-m", "eol.agent"]` in Dockerfile
- Env var: `os.environ.get("EOL_AGENT_ID", "")` for Foundry agent ID
- Postgres DSN: `PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD` env vars
  (see `services/api-gateway/runbook_rag.py` for the resolver pattern)

### Integration Points
- `agents/orchestrator/agent.py` — 3 locations: `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`,
  system prompt routing rules, `AgentTarget` list
- `agents/shared/routing.py` — add `"eol"` entry to `QUERY_DOMAIN_KEYWORDS`
- PostgreSQL `eol_cache` table — new migration `003_create_eol_cache_table.sql` alongside
  existing migrations in `services/api-gateway/migrations/`
- `agents/tests/integration/` — integration test directory for new agent handoff tests

### New Dependency
- `httpx` — async HTTP client for endoflife.date API and MS Lifecycle API calls.
  Check `agents/requirements-base.txt` — if absent, add to `agents/eol/requirements.txt`
  (and base if other future agents will also need it).

</code_context>

<specifics>
## Specific Ideas

- **Source routing by product type**: Microsoft products (Windows Server, SQL Server, .NET,
  Exchange, IIS, Azure services) → MS Lifecycle API first; everything else (Linux distros,
  Python, Node.js, open-source databases, Kubernetes) → endoflife.date. Fallback to
  endoflife.date if MS API returns no result for a Microsoft product.
- **Proactive scan + incident creation**: `scan_estate_eol()` is a dedicated `@ai_function`
  tool that returns a scan report AND creates API gateway incidents for threshold crossings.
  Intended for daily timer invocation. Dedup logic prevents flooding if run multiple times.
- **90/60/30 day thresholds**: Create one incident per threshold per resource per product
  (idempotent check). Risk level: 30-day and already-EOL → `"high"`, 60/90-day → `"medium"`.
- **endoflife.date API**: Free, public, no auth required. Endpoint pattern:
  `GET https://endoflife.date/api/{product}/{version}.json`. Covers 200+ products.
- **PostgreSQL cache table**: Named `eol_cache`, lives in the same Flexible Server as runbooks.
  New migration `003_create_eol_cache_table.sql`. 24h TTL, synchronous refresh on cache miss.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 12-eol-domain-agent-with-multi-source-internet-search-and-postgresql-caching*
*Context gathered: 2026-03-31*
