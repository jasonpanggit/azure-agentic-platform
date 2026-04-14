---
title: Upgrade Azure MCP Server to v2
date: 2026-04-14
priority: medium
---

# Todo: Upgrade Azure MCP Server to v2

## Context

Azure MCP Server v2.0.0 GA'd on April 10, 2026. The project repo has moved from
`Azure/azure-mcp` (archived) to `microsoft/mcp`. The package reference in CLAUDE.md
and any Terraform/Docker configs referencing `@azure/mcp` are now stale.

## Tasks

- [ ] Update package reference: `@azure/mcp` (npm) → new distribution from `microsoft/mcp`
      (PyPI: `msmcp-azure`; npm equivalent from new repo)
- [ ] Update CLAUDE.md Azure MCP Server section with new repo, package name, and version
- [ ] Update any Dockerfile or Container App configs that pull the MCP server image
      (Docker image is ~60% smaller in v2 — worth the update for cold start)
- [ ] Verify Terraform configs referencing the MCP server container image tag
- [ ] Smoke-test existing tools still work post-upgrade (monitor, storage, compute, etc.)
- [ ] Note: startup time improves from ~20s → 1-2s — verify in Container Apps health checks

## New Tools to Wire Up (follow-on, separate phase)

After upgrade is stable, evaluate:
- `containerapps` namespace — inspect own agent Container App health
- `advisor` namespace — enhance SRE agent with structured Advisor recommendations

## Do NOT chase yet

- `3.0.0-beta.1` — breaking namespace changes + MCP protocol v1.1.0; wait for GA
