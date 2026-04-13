---
title: Azure MCP v2 Agent Enhancements
trigger_condition: Azure MCP v2 upgrade complete and stable on main
planted_date: 2026-04-14
---

# Seed: Azure MCP v2 Agent Enhancements

## Trigger

Execute this seed after the Azure MCP v2 upgrade is complete and the existing
tools have been smoke-tested in production.

## What to Build

### 1. SRE Agent — `advisor` namespace

The SRE agent currently surfaces Azure Advisor recommendations via ARM/Monitor
path. The new native `advisor` namespace in v2 gives structured access to:
- Cost recommendations
- Reliability recommendations
- Performance recommendations
- Operational excellence recommendations

**Enhancement:** Wire `advisor` tools into the SRE agent as first-class tools
alongside existing service health and change analysis tools.

### 2. Self-Monitoring via `containerapps` namespace

The platform's agents run on Container Apps. Today there's no way to inspect
their own deployment health from within an agent conversation. The new
`containerapps` namespace enables:
- Revision status and traffic split
- Replica counts and scaling events
- Container App health/readiness

**Enhancement:** Add a lightweight ops capability — an operator can ask
"why is the compute agent slow?" and get back Container App health data.
Could live in the Orchestrator or SRE agent.

## What to Hold Off On (review later)

These were explicitly deferred during the April 14, 2026 exploration session.
Review when the platform has matured past MVP:

| Namespace | Reason Deferred |
|---|---|
| `pricing` | Not core to AIOps value; no current use case |
| `azuremigrate` | Relevant only if resource lifecycle tracking enters scope |
| `wellarchitectedframework` | Useful for governance reviews; not operational |
| `3.0.0-beta.1` | Breaking namespace changes + MCP protocol v1.1.0 — wait for GA |

## References

- Research session: 2026-04-14
- v2 release: `microsoft/mcp` repo, `Azure.Mcp.Server 2.0.0`, April 10, 2026
- 260+ tools (up from ~131 in last v1 release)
