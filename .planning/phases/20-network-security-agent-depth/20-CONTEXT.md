# Phase 20: Network & Security Agent Depth - Context

**Gathered:** 2026-04-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the Network, Security, and SRE domain agents genuine diagnostic depth. Each agent currently
has only skeleton tools that return empty dicts. After this phase:

- **Network agent** — 3 existing tools completed (NSG rules, VNet topology, load balancer health)
  + 3 new tools: flow logs query, ExpressRoute health, connectivity diagnostics (via Network Watcher)
  = 6 fully implemented network tools
- **Security agent** — 3 existing tools completed (Defender alerts, Key Vault diagnostics, IAM changes)
  + new tools: secure score, RBAC assignments, Policy compliance, public endpoint scan
  = fully implemented security tool suite
- **SRE agent** — 3 existing tools completed (availability metrics, performance baselines, propose_remediation)
  + 4 new tools: Service Health, Advisor recommendations, Change Analysis, cross-domain correlation
  = fully implemented SRE tool suite

All tools use real azure-mgmt-* SDK calls (not stubs). The roadmap names specific tools but
Claude has discretion to adjust tool names and signatures based on actual Azure SDK availability
(e.g., "connectivity diagnostics" maps to Network Watcher; use best judgment throughout).

**What this phase does NOT do:**
- No new Container App deployments
- No Terraform changes (agents are already deployed)
- No changes to orchestrator routing logic
- No new API gateway endpoints

</domain>

<decisions>
## Implementation Decisions

### Tool Implementation Depth

- **D-01:** All new and existing stub tools get **full real azure-mgmt-* SDK implementations** —
  same quality as the compute agent (685 lines) and patch agent (870 lines). Every tool makes
  live Azure SDK calls with proper error handling (never raises, returns structured error dicts).
- **D-02:** Follow the **established tool pattern**: `start_time = time.monotonic()` at entry;
  `duration_ms` recorded in both `try` and `except` blocks; return structured dicts with
  `query_status: "success" | "error"` and `error_message` on failure.
- **D-03:** Each tool wraps SDK call with `instrument_tool_call()` from `shared.otel` (existing
  pattern in all agents — copy from network/security/sre agent.py header).

### New Tool List & Naming

- **D-04:** Use roadmap intent as the guide but **adjust tool names to match what the Azure SDK
  actually provides**. Don't force a name that doesn't map to a clean SDK surface.
  - "Connectivity diagnostics" → likely `check_connectivity` using azure-mgmt-network's
    `network_watchers.check_connectivity` or similar Network Watcher API
  - "ExpressRoute health" → `query_expressroute_health` using `express_route_circuits`
  - "Cross-domain correlation" → SRE tool that calls multiple domain query functions to build
    a unified incident correlation view
  - Claude's discretion on exact function names, parameter shapes, and return structures
- **D-05:** The **existing 3–4 tools in each agent are stubs** — they count toward the roadmap's
  "6 Network / 6 Security / 4 SRE" target. Complete them + add the delta to hit those totals.

### Azure SDK Strategy

- **D-06:** Implement real azure-mgmt-* SDK calls in all `@ai_function` wrappers:
  - Network → `azure-mgmt-network` (already in requirements.txt, already used as stub pattern)
  - Security → `azure-mgmt-security` (Defender alerts, secure score) + `azure-mgmt-authorization`
    (RBAC assignments) + `azure-mgmt-policyinsights` (Policy compliance)
  - SRE → `azure-mgmt-monitor` (Service Health, Change Analysis) + `azure-mgmt-advisor`
    (Advisor recommendations)
- **D-07:** **Expand ALLOWED_MCP_TOOLS** in each agent to include relevant Azure MCP Server tools
  alongside the SDK tools. This gives agents dual access — direct SDK for precision queries,
  MCP for broader Azure surface coverage:
  - Network: add `compute.list_virtual_machines` (for VM NIC inspection), any network-relevant
    monitor/advisor tools
  - Security: add `policy.list_assignments` (if available), `advisor.list_recommendations`
    (for security recommendations)
  - SRE: existing MCP tools already include `advisor.list_recommendations` and
    `resourcehealth.list_events` — expand as Claude sees fit
- **D-08:** Check `requirements.txt` in each agent directory before adding new SDK packages.
  Prefer packages already in the agent's requirements over adding new deps.

### Agent System Prompts

- **D-09:** Update each agent's `NETWORK_AGENT_SYSTEM_PROMPT` / `SECURITY_AGENT_SYSTEM_PROMPT` /
  `SRE_AGENT_SYSTEM_PROMPT` in agent.py to reference the new tools and describe when to use them.
  Also update the `ChatAgent` tool list (the `tools=[...]` kwarg passed at instantiation).
- **D-10:** Maintain existing TRIAGE-002/003/004 and REMEDI-001 constraints in system prompts —
  these are locked requirements from Phase 2.

### Test Coverage

- **D-11:** Create **dedicated per-agent unit test files**:
  - `agents/tests/network/test_network_tools.py`
  - `agents/tests/security/test_security_tools.py`
  - `agents/tests/sre/test_sre_tools.py`
  - Follow the pattern of `test_patch_tools.py` and `test_eol_tools.py` — mock azure-mgmt-* clients
    at the SDK level, test both success and error paths for every tool.
- **D-12:** Also **extend integration tests** — update `agents/tests/integration/test_triage.py`
  to include new tool scenarios for the 3 agents (e.g., NSG triage flow, Defender alert triage,
  SRE service health flow).
- **D-13:** Each unit test file should achieve **≥80% coverage** on its respective tools.py module.
  Error path (SDK raises exception → tool returns error dict) must be tested.

### Claude's Discretion

- Exact parameter names and return dict key names for each tool (follow compute/patch patterns)
- Whether to create `agents/tests/network/__init__.py` etc. if not already present
- Order of tool implementation within each agent
- Whether `cross_domain_correlation` for SRE calls other agents' tools directly or uses Monitor
  data to simulate cross-domain insight (prefer the Monitor-based approach to avoid circular deps)
- Specific azure-mgmt-* method signatures — use latest SDK docs

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Agent Pattern Reference
- `agents/compute/tools.py` — Full reference implementation for @ai_function depth and SDK call pattern
- `agents/patch/tools.py` — Second reference for azure-mgmt-compute pattern + error handling
- `agents/network/tools.py` — Current state (stubs); shows existing structure to extend
- `agents/security/tools.py` — Current state (stubs); shows existing structure to extend
- `agents/sre/tools.py` — Current state (stubs); shows existing structure to extend

### Agent Instantiation Pattern
- `agents/network/agent.py` — Shows ChatAgent instantiation, ALLOWED_MCP_TOOLS, system prompt pattern
- `agents/security/agent.py` — Same for security agent
- `agents/sre/agent.py` — Same for SRE agent

### Test Pattern Reference
- `agents/tests/patch/test_patch_tools.py` — Unit test reference (mock azure-mgmt SDK, error paths)
- `agents/tests/eol/test_eol_tools.py` — Second unit test reference
- `agents/tests/integration/test_triage.py` — Integration test to extend

### Shared Infrastructure
- `agents/shared/auth.py` — `get_agent_identity()` and `get_foundry_client()` patterns
- `agents/shared/otel.py` — `instrument_tool_call()` and `setup_telemetry()` patterns

### Requirements
- `.planning/REQUIREMENTS.md` — TRIAGE-002, TRIAGE-003, TRIAGE-004, REMEDI-001 constraints
- `.planning/ROADMAP.md` §Phase 20 — Authoritative tool list by agent (intent, not binding names)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `shared/auth.py` — `get_agent_identity()` used identically in all tool files
- `shared/otel.py` — `instrument_tool_call()` / `setup_telemetry()` used identically
- `agents/compute/tools.py` — Full azure-mgmt-compute usage pattern to port to other agents
- `agents/patch/tools.py` — azure-mgmt-compute + Log Analytics pattern for reference

### Established Patterns
- `@ai_function` decorator from `agent_framework` — tool registration
- `ALLOWED_MCP_TOOLS: List[str]` module-level constant — per-agent MCP allowlist
- Tool functions never raise — always `try/except`, return `{"query_status": "error", "error_message": ...}`
- `start_time = time.monotonic()` at entry; `duration_ms` in both branches
- `instrument_tool_call(tracer, agent_name, agent_id, tool_name, tool_parameters, correlation_id="", thread_id="")` wraps the SDK call

### Integration Points
- Each agent's `agent.py` registers tools in `ChatAgent(tools=[tool_fn1, tool_fn2, ...])`
- `ALLOWED_MCP_TOOLS` is consumed by the Foundry agent server adapter
- Tests mock at `azure.mgmt.*.XxxClient` level — see test_patch_tools.py for mock pattern

### Current State (Phase 20 baseline)
- Network: 4 tools, all stubs, 206 lines total
- Security: 3 tools, all stubs, 165 lines total
- SRE: 3 tools, all stubs (but propose_remediation is functionally complete — no SDK needed), 182 lines total
- No dedicated unit tests for these agents

</code_context>

<specifics>
## Specific Ideas

No specific "I want it like X" moments — standard azure-mgmt-* patterns apply.
Follow the compute and patch agents as the depth reference.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 20-network-security-agent-depth*
*Context gathered: 2026-04-10*
