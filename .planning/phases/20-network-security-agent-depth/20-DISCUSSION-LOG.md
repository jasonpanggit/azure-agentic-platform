# Phase 20: Network & Security Agent Depth - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-10
**Phase:** 20-network-security-agent-depth
**Areas discussed:** Tool implementation depth, New tool list & naming, Azure SDK strategy per agent, Test coverage approach

---

## Tool Implementation Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Full real implementation | Real azure-mgmt-* SDK calls in every tool, same quality as compute and patch agents | ✓ |
| Rich typed stubs | Structured stubs with realistic return shapes but no live SDK calls | |
| Hybrid (Network real, others stub) | Real SDK calls for Network tools only, stubs for Security and SRE | |

**User's choice:** Full real implementation
**Notes:** Phase goal explicitly says "genuine diagnostic depth" — full SDK implementation is the intended end-state.

---

## New Tool List & Naming

| Option | Description | Selected |
|--------|-------------|----------|
| Follow roadmap exactly | Implement exactly what the roadmap names without deviation | |
| Adjust names as needed | Use roadmap as intent, adjust tool names to match what Azure SDK actually provides | ✓ |
| Custom tool set | User-defined tool set differing from roadmap | |

**User's choice:** Adjust names as needed
**Notes:** Claude has discretion on exact function names, parameter shapes, return structures. E.g., "connectivity diagnostics" maps to Network Watcher API rather than a literal tool name.

---

## Azure SDK Strategy Per Agent

| Option | Description | Selected |
|--------|-------------|----------|
| azure-mgmt-* SDKs directly | Use azure-mgmt-* packages in @ai_function wrappers, consistent with existing pattern | |
| MCP tools where possible, SDK for gaps | Prefer Azure MCP Server tools, fall back to SDK only for gaps | |
| Both SDK + expanded MCP allowlist | Real azure-mgmt-* implementations + expand ALLOWED_MCP_TOOLS for dual access | ✓ |

**User's choice:** Both SDK + expanded MCP allowlist
**Notes:** Agents get both direct SDK precision AND broader MCP coverage. Each agent's ALLOWED_MCP_TOOLS list expands to include new relevant tools.

---

## Test Coverage Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated per-agent test files | New test_network_tools.py, test_security_tools.py, test_sre_tools.py files | |
| Extend existing integration tests | Add new tool tests to existing test_triage.py, test_mcp_tools.py | |
| Both unit + integration tests | Dedicated per-agent unit files + extended integration test coverage | ✓ |

**User's choice:** Both unit + integration tests
**Notes:** Follow test_patch_tools.py and test_eol_tools.py patterns for unit tests. Also extend test_triage.py with new tool scenarios. ≥80% coverage target per tools.py module.

---

## Claude's Discretion

- Exact parameter names and return dict key structures for each new tool
- Whether to create `agents/tests/network/__init__.py` etc. (if missing)
- Order of tool implementation within each agent
- How `cross_domain_correlation` for SRE is implemented (prefer Monitor-based approach to avoid circular deps)
- Specific azure-mgmt-* method signatures (use latest SDK docs)

## Deferred Ideas

None — discussion stayed within phase scope.
