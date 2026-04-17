# Agents

This directory contains all 9 domain specialist agents plus the orchestrator for the Azure Agentic Platform. Each agent is a Microsoft Agent Framework `ChatAgent` deployed as a Foundry Hosted Agent on Azure Container Apps. The orchestrator receives all requests and routes them to the appropriate domain specialist via connected-agent tools; domain agents never receive requests directly.

## Agent Map

| Directory | Container App | Role |
|-----------|--------------|------|
| [`orchestrator/`](orchestrator/) | `ca-orchestrator-prod` | Central router — classifies incidents and delegates to domain agents |
| [`compute/`](compute/) | `ca-compute-prod` | VM diagnostics, metrics, resource health, OS inventory |
| [`network/`](network/) | `ca-network-prod` | NSG, VNet, load balancers, connectivity checks |
| [`storage/`](storage/) | `ca-storage-prod` | Blob, Files, ADLS Gen2, managed disks |
| [`security/`](security/) | `ca-security-prod` | Defender alerts, Key Vault, RBAC drift, policy compliance |
| [`arc/`](arc/) | `ca-arc-prod` | Arc-enabled servers, Kubernetes, and data services via custom Arc MCP Server |
| [`sre/`](sre/) | `ca-sre-prod` | Cross-domain correlation, availability, perf baselines — catch-all fallback |
| [`patch/`](patch/) | `ca-patch-prod` | Patch compliance and installation history via Azure Update Manager |
| [`eol/`](eol/) | `ca-eol-prod` | End-of-life detection via endoflife.date and Microsoft Lifecycle APIs |
| [`appservice/`](appservice/) | `ca-appservice-prod` | App Service and Function App health and performance |
| [`containerapps/`](containerapps/) | `ca-containerapps-prod` | Container Apps health, revisions, and scale |
| [`database/`](database/) | `ca-database-prod` | Cosmos DB, PostgreSQL Flexible Server, and Azure SQL diagnostics |
| [`finops/`](finops/) | `ca-finops-prod` | Cost analysis, idle resource detection, budget forecasting |
| [`messaging/`](messaging/) | `ca-messaging-prod` | Service Bus and Event Hubs health and queue diagnostics |
| [`shared/`](shared/) | (library) | Auth, telemetry, envelope, routing, approval, runbook, and SOP utilities |
| [`tests/`](tests/) | (CI) | Unit and integration test suites for all agents |

## Key Files

- `__init__.py` — package marker
- `Dockerfile.base` — shared base image layer for all agent containers
- `requirements-base.txt` — common Python dependencies for all agents

## Architecture Notes

- All agents use `DefaultAzureCredential` for Azure authentication (no stored secrets).
- Azure MCP Server (`@azure/mcp` v2.0.0) is mounted on compute, network, storage, security, and SRE agents via Foundry tool connections; Arc agent mounts the custom Arc MCP Server.
- No agent executes remediation without an explicit human approval via the HITL approval flow in `shared/approval_manager.py`.
- See [`orchestrator/README.md`](orchestrator/README.md) for the full routing architecture.
