---
title: Azure MCP Server v2 — Exploration Notes
date: 2026-04-14
context: gsd-explore session on upgrading Azure MCP Server to v2
---

# Azure MCP Server v2 — Exploration Notes

## What Changed

- **Repo moved:** `Azure/azure-mcp` (archived Aug 25, 2025) → `microsoft/mcp`
- **Package:** `@azure/mcp` npm is stale → new distribution via `microsoft/mcp`
  - PyPI: `msmcp-azure`
  - Also on NuGet, npm, Docker, and new `.mcpb` MCP Bundles format
- **Version:** `Azure.Mcp.Server 2.0.0` GA'd April 10, 2026
- **Tool count:** ~131 (v0.5.8) → 260+ in v2 (~2x increase)

## New Namespaces in v2

`advisor`, `compute`, `containerapps`, `deviceregistry`, `fileshares`,
`functions`, `azuremigrate`, `policy`, `pricing`, `servicefabric`,
`storagesync`, `wellarchitectedframework`

## Security Improvements (Directly Relevant to AAP)

- SSRF protection
- KQL injection prevention with query parameterization (Monitor, Kusto)
- SQL injection prevention (MySQL, PostgreSQL, Cosmos DB)
- URI validation across Storage/Compute/Service Bus
- User confirmation prompts for destructive operations (MCP elicitation)

## Operational Improvements

- Startup time: ~20s → **1–2 seconds**
- Docker image size: down ~60% (AMD64 + ARM64)
- Remote HTTP deployment with Entra ID + OBO auth now supported
- Azure Government and Azure China sovereign clouds now supported

## What Stays the Same

- **Arc gap persists:** No Arc-enabled servers/Kubernetes or VNet/NSG tools in v2
- Custom Arc MCP Server remains necessary for AAP

## What's Coming (Do Not Chase Yet)

- `3.0.0-beta.1` in progress: namespace realignment to `Microsoft.Mcp.Core` +
  MCP protocol v1.1.0 — likely breaking changes. Wait for GA.

## AAP Decision

1. **Upgrade now** — package reference update, startup improvement, security hardening
2. **Enhance after upgrade** — `advisor` for SRE agent, `containerapps` for self-monitoring
3. **Defer** — `pricing`, `azuremigrate`, `wellarchitectedframework`, v3 beta
