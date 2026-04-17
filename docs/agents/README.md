# docs/agents

Specification documents for each agent in the platform. Each `.spec.md` file defines the agent's role, available tools, system prompt guidance, and handoff contracts with other agents.

## Contents

| File | Agent |
|------|-------|
| `orchestrator-agent.spec.md` | Central router — intent classification and domain handoffs |
| `compute-agent.spec.md` | VM diagnostics, metrics, activity logs, resource health |
| `network-agent.spec.md` | NSG, VNet, peering, flow logs, ExpressRoute, connectivity |
| `storage-agent.spec.md` | Storage account operations and diagnostics |
| `security-agent.spec.md` | Defender alerts, Key Vault, IAM, secure score, policy |
| `arc-agent.spec.md` | Arc-enabled servers and Kubernetes via custom Arc MCP |
| `sre-agent.spec.md` | Availability, perf baselines, Advisor, change analysis |
| `patch-agent.spec.md` | ARG-based patch assessment and Update Manager history |
| `eol-agent.spec.md` | End-of-life detection via endoflife.date + MS Lifecycle |
| `database-agent.spec.md` | Cosmos DB and PostgreSQL diagnostics |
| `aks-agent.spec.md` | AKS cluster and workload health |
| `appservice-agent.spec.md` | App Service and Function App diagnostics |
| `containerapps-agent.spec.md` | Container Apps environment and revision health |
| `messaging-agent.spec.md` | Event Hubs and Service Bus diagnostics |
| `finops-agent.spec.md` | Cost analysis and budget alerting |
