# Azure Agentic Platform (AAP)

An enterprise-grade AI operations platform that uses a domain-specialist multi-agent architecture to perform continuous monitoring, auditing, alerting, triage, troubleshooting, and automated remediation across all Azure subscriptions and Arc-enabled resources (servers, Kubernetes, data services).

**Core Value:** Operators can understand, investigate, and resolve any Azure infrastructure issue — across all subscriptions and Arc-connected resources — through a single intelligent platform that shows its reasoning transparently and never acts without human approval.

## Architecture Overview

```
Web UI (Next.js)  ←→  API Gateway (FastAPI)  ←→  Foundry Agent Service
                                                         │
                        ┌────────────────────────────────┤
                        │                                │
                  Orchestrator Agent              Domain Agents
                        │                                │
              ┌─────────┴──────────┐        compute / network / storage /
              │                    │        security / arc / sre / patch /
        Azure MCP Server    Arc MCP Server  eol / appservice / containerapps /
        (GA, v2.0.0)       (custom FastMCP) database / finops / messaging
```

## Key Features

- **Multi-agent AIOps** — 9 domain specialist agents route through a central orchestrator via Foundry connected agent handoffs
- **Real-time detection** — Azure Monitor → Event Hub → Fabric Eventhouse (KQL) → Fabric Activator → incident ingestion
- **Conversational + dashboard UI** — Next.js 15 with co-equal chat panel and live operational dashboards (Alerts, Audit, Topology, Resources, Observability, Patch)
- **Teams integration** — two-way agent interaction, Adaptive Card approval flows, proactive alert delivery
- **Human-in-the-loop** — no automated remediation without explicit operator approval

## Repository Structure

| Directory | Description |
|-----------|-------------|
| [`agents/`](agents/README.md) | Domain specialist agents (orchestrator + 13 specialists + shared utilities) |
| [`services/`](services/README.md) | Platform services: API gateway, MCP servers, detection plane, Teams bot, web UI |
| [`terraform/`](terraform/README.md) | Infrastructure as Code (azurerm + azapi providers) |
| [`fabric/`](fabric/README.md) | Fabric Eventhouse KQL schemas, policies, and user data functions |
| [`sops/`](sops/README.md) | Standard Operating Procedures by domain |
| [`scripts/`](scripts/README.md) | Operational scripts: incident simulation, runbook seeding, auth validation |
| [`docs/`](docs/README.md) | Architecture docs, agent specs, operations guides |
| [`tests/`](tests/README.md) | Integration and evaluation test suites |
| [`e2e/`](e2e/README.md) | Playwright end-to-end tests |
| [`migrations/`](migrations/README.md) | PostgreSQL database migrations |
| [`docker/`](docker/README.md) | Docker build files (GitHub Actions runner) |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | Microsoft Agent Framework (`agent-framework` 1.0.0rc5) |
| Agent hosting | Azure AI Foundry Hosted Agents + Container Apps |
| Agent SDK | `azure-ai-projects` 2.0.1 (GA) |
| MCP tools | Azure MCP Server v2.0.0 (GA) + Custom Arc MCP Server |
| Frontend | Next.js 15, Tailwind CSS v3, shadcn/ui (New York) |
| API gateway | FastAPI (Python) |
| Detection plane | Fabric Eventhouse + Fabric Activator |
| Teams bot | `@microsoft/teams.js` (new Teams SDK, TypeScript) |
| Databases | Cosmos DB (hot-path), PostgreSQL + pgvector (runbooks/RAG) |
| IaC | Terraform (`azurerm ~> 4.65.0`, `azapi ~> 2.9.0`) |
| Testing | pytest, Jest, Playwright |

## Getting Started

### Prerequisites

- Python ≥ 3.10
- Node.js ≥ 18
- Azure subscription with Foundry project provisioned
- Terraform ≥ 1.5

### Local Development

```bash
# Python dependencies
pip install -e ".[dev]"

# Web UI
cd services/web-ui && npm install && npm run dev

# API gateway
cd services/api-gateway && uvicorn main:app --reload

# Run tests
pytest                          # all Python tests
cd services/web-ui && npm test  # frontend tests
cd e2e && npx playwright test   # E2E tests
```

### Infrastructure

```bash
cd terraform/envs/prod
terraform init
terraform plan -var-file=credentials.tfvars -var-file=terraform.tfvars
terraform apply -var-file=credentials.tfvars -var-file=terraform.tfvars
```

See [`docs/ops/`](docs/ops/README.md) for full operational runbooks.
