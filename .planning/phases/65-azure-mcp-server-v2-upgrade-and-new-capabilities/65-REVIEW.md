# Phase 65 — Code Review
## Azure MCP Server v2 Upgrade and New Capabilities
**Commits:** `2e40eb3` → `acd96c4`
**Reviewed:** 2026-04-14
**Files:** 4 (Dockerfile, agents/sre/tools.py, agents/sre/agent.py, CLAUDE.md)

---

## Summary

All four changes are correct, focused, and consistent with project conventions. No security
vulnerabilities or correctness bugs were introduced. The phase is a clean, minimal upgrade: one
ARG bump, three allowlist entries, one prompt section, and doc updates. The most significant
issue found is a **HIGH** test regression — the `TestAllowedMcpTools` class in
`agents/tests/sre/test_sre_tools.py` hardcodes an expected count of `6` entries and an expected
list of 6 specific tool names, both of which are now stale after the 3 new `containerapps` tools
were added.

---

## Findings

### HIGH

#### H-01 — Test suite now fails: `ALLOWED_MCP_TOOLS` count and membership assertions are stale

**File:** `agents/tests/sre/test_sre_tools.py` (not changed in this phase, but broken by it)
**Lines:** 30–47

```python
# test_allowed_mcp_tools_has_exactly_six_entries  ← FAILS: list is now 9
assert len(ALLOWED_MCP_TOOLS) == 6

# test_allowed_mcp_tools_contains_expected_entries  ← PASSES but incomplete
# Does not assert the 3 new containerapps entries exist
```

**Impact:** `pytest agents/tests/sre/test_sre_tools.py::TestAllowedMcpTools` fails with
`AssertionError: assert 9 == 6`. Any CI run exercising the SRE test suite will break.

**Fix required:** Update the count assertion from `6` to `9` and add the three new tool names
to the `expected` list in `test_allowed_mcp_tools_contains_expected_entries`:
```python
"containerapps.list_apps",
"containerapps.get_app",
"containerapps.list_revisions",
```

---

### MEDIUM

#### M-01 — CONTEXT.md planned a `query_container_app_health` Python `@ai_function` tool; it was not implemented

**File:** `.planning/phases/65-.../65-CONTEXT.md` (decision record, not a code file)
**Context:** The phase context document specifies:
> Add new `@ai_function` tool: `query_container_app_health(container_app_name, resource_group)`
> Uses `azure-mgmt-appcontainers` SDK (lazy import pattern)

The implementation instead took a lighter path: only the MCP allowlist entries were added and
the system prompt was updated to instruct the LLM to call the MCP tools directly. No Python
`@ai_function` wrapper was added, and `azure-mgmt-appcontainers` was not added to
`agents/sre/requirements.txt`.

**Impact:** Not a bug — the MCP-only path is fully functional and consistent with how MCP tools
work in this platform. The SUMMARY.md documents this as no deviation. However, there is a gap:
when the MCP server is unreachable, the SRE agent has no SDK-based fallback for Container Apps
health. All other SRE monitoring domains have Python `@ai_function` SDK fallbacks.

**Recommendation:** Track the SDK-backed `query_container_app_health` tool as a Plan 65-2 task
(already noted in SUMMARY.md as "next phase readiness") to maintain consistency. Not blocking.

#### M-02 — Module docstring in `tools.py` uses informal `containerapps (list_apps, get_app, list_revisions)` notation

**File:** `agents/sre/tools.py`, lines 6–7

```python
"""...
    containerapps (list_apps, get_app, list_revisions)
"""
```

All other entries in the docstring use the canonical `namespace.operation` dotted format
(`monitor.query_logs`, `resourcehealth.get_availability_status`, etc.). The new line uses a
different grouping syntax, making the docstring inconsistent and potentially confusing to
readers parsing what the allowlist looks like.

**Recommendation:** Expand to three separate lines matching the established format:
```
    containerapps.list_apps, containerapps.get_app, containerapps.list_revisions
```

---

### LOW

#### L-01 — Dockerfile uses `node:20` (floating major tag) — no SHA or minor version pin

**File:** `services/azure-mcp-server/Dockerfile`, line 11

```dockerfile
FROM node:20
```

`node:20` resolves to the latest Node 20 patch release at build time. This means two ACR builds
on different days can produce different base images, potentially introducing unreviewed OS/runtime
changes. The Node image in this container only runs the reverse proxy (`proxy.js`, 26 lines) and
`azmcp`; the attack surface is small, but image reproducibility is a best practice for production
Container Apps.

**Recommendation:** Pin to a specific digest or at minimum a patch version:
```dockerfile
FROM node:20.19.0-bookworm-slim
```
Using `-slim` also reduces image size by ~400 MB. Not blocking for this phase, but worth
addressing in a follow-up infra hardening pass.

#### L-02 — `proxy.js` passes all client request headers through to `azmcp` unfiltered

**File:** `services/azure-mcp-server/proxy.js`, line 13

```javascript
headers: req.headers,
```

All inbound HTTP headers (including `Host`, `X-Forwarded-For`, `Authorization`, etc.) are
forwarded verbatim to `azmcp`. Since the Container App uses internal-only ingress
(`external_enabled = false`), only traffic from within the Container Apps environment reaches
this proxy, significantly limiting the exposure. The security comment in the Dockerfile CMD
block (SEC-001) documents this mitigating boundary.

**Recommendation:** As a defence-in-depth measure, strip or override the `Host` header before
forwarding to `azmcp localhost:5000`:
```javascript
headers: { ...req.headers, host: '127.0.0.1' },
```
This prevents any host-header injection from influencing `azmcp`'s routing. Low priority given
the internal-only network boundary.

#### L-03 — `advisor` namespace: `advisor.get_recommendation` allowlist addition was deferred but not explicitly noted

**File:** `agents/sre/tools.py` — `ALLOWED_MCP_TOOLS`
**Context:** `65-CONTEXT.md` line 41 states:
> Add `advisor.get_recommendation` to `ALLOWED_MCP_TOOLS` if available in v2 (check namespace)

This was silently skipped — no note in SUMMARY.md about whether it was verified absent or
explicitly deferred. If `advisor.get_recommendation` does exist in v2, the SRE agent cannot
call it to drill into a specific recommendation after `advisor.list_recommendations` returns
a summary.

**Recommendation:** Verify `advisor.get_recommendation` existence in v2 tool list and either
add it to `ALLOWED_MCP_TOOLS` or add a comment explaining why it was excluded. Not blocking.

#### L-04 — CLAUDE.md "MCP Surfaces" architecture line omits some of the 7 new v2 namespaces

**File:** `CLAUDE.md`, architecture section — MCP Surfaces

```markdown
- **Azure MCP Server** (v2.0.0 GA) — ... covers ARM, Compute, Storage, Databases, Monitoring,
  Security, Messaging, `containerapps`, Functions
```

The Covered Services table correctly lists all 7 new namespaces (`containerapps`, `deviceregistry`,
`functions`, `azuremigrate`, `policy`, `pricing`, `wellarchitectedframework`), but the
architecture summary line only calls out `containerapps` and `Functions`. `deviceregistry`,
`azuremigrate`, `pricing`, and `wellarchitectedframework` are absent from the summary.

**Impact:** Cosmetic only — readers consulting the architecture section get an incomplete picture
of v2 coverage. The full table above it is accurate.

**Recommendation:** Either extend the summary line to name all new high-value namespaces or
replace the inline list with a reference to the Covered Services table. Not blocking.

---

## Security Assessment

| Check | Result |
|---|---|
| Hardcoded secrets | ✅ None |
| Injection vectors (KQL, shell, HTTP) | ✅ None introduced; MCP proxy passes headers verbatim (L-02, low risk) |
| Auth bypass | ✅ None; `DefaultAzureCredential` managed identity unchanged |
| Non-root container user | ✅ `USER mcp` set in Dockerfile (pre-existing, not regressed) |
| Wildcard MCP tools | ✅ All 3 new entries are explicit dotted names, no wildcards |
| New network surfaces | ✅ No new ingress; containerapps is an MCP call over existing internal path |

---

## Code Correctness Assessment

| Check | Result |
|---|---|
| Tool name format (`namespace.operation`) | ✅ All 3 new entries match established format |
| Tool names match v2 namespace | ✅ `containerapps.list_apps`, `.get_app`, `.list_revisions` match CLAUDE.md Covered Services table |
| Allowlist consistent between tools.py and agent.py | ✅ All 3 new names appear in both ALLOWED_MCP_TOOLS list and system prompt |
| System prompt / allowlist sync | ✅ `{allowed_tools}` format string in agent.py correctly includes new entries |
| No wildcards | ✅ Confirmed |
| Existing tools unaffected | ✅ No existing ALLOWED_MCP_TOOLS entries modified |

---

## Documentation Accuracy Assessment

| Check | Result |
|---|---|
| Dockerfile comment matches ARG version | ✅ Comment says `v2.0.0 GA`, ARG is `2.0.0` |
| CLAUDE.md version table updated | ✅ `2.0.0` in Summary table |
| CLAUDE.md repo reference updated | ✅ `microsoft/mcp (formerly Azure/azure-mcp, now archived)` |
| Covered Services table accurate | ✅ Matches known v2 namespace list |
| Architecture section updated | ✅ `v2.0.0 GA` annotation and `containerapps` added |
| Version consistency across files | ⚠️ Minor: architecture summary line (L-04) doesn't list all new namespaces |

---

## Dockerfile Best Practices Assessment

| Check | Result |
|---|---|
| Non-root user | ✅ `USER mcp` in place |
| Layer cache optimization | ✅ `npm install` + `npm cache clean` in single `RUN` layer |
| COPY before USER switch | ✅ `proxy.js` copied before `USER mcp` so permissions are correct |
| ARG-driven version (no hardcoded) | ✅ `ARG AZURE_MCP_VERSION=2.0.0` used in `npm install` |
| Base image pinning | ⚠️ `node:20` floating tag (L-01) |
| Image size | ⚠️ `node:20` full image; `-slim` variant would reduce size ~400 MB (L-01) |
| Secrets in image | ✅ None |

---

## Action Items

| Priority | ID | Action | File |
|---|---|---|---|
| **HIGH** | H-01 | Fix `TestAllowedMcpTools`: update count `6→9`, add 3 containerapps entries to expected list | `agents/tests/sre/test_sre_tools.py` |
| MEDIUM | M-01 | Track `query_container_app_health` Python tool as Plan 65-2 (already noted in SUMMARY) | `agents/sre/tools.py` |
| MEDIUM | M-02 | Expand docstring to use canonical dotted format for containerapps entries | `agents/sre/tools.py` |
| LOW | L-01 | Pin base image to specific patch + `-slim` variant in a follow-up infra pass | `services/azure-mcp-server/Dockerfile` |
| LOW | L-02 | Override `host` header in proxy forward as defence-in-depth | `services/azure-mcp-server/proxy.js` |
| LOW | L-03 | Verify `advisor.get_recommendation` in v2 and explicitly include or exclude | `agents/sre/tools.py` |
| LOW | L-04 | Extend architecture MCP Surfaces line to list all new v2 namespaces | `CLAUDE.md` |

---

## Verdict

**Ready to ship with one required fix (H-01).** The phase delivers its intended scope cleanly.
H-01 is a CI-breaking test regression that must be resolved before the branch merges. All
other findings are low-risk cosmetic or follow-up items. No security issues.
