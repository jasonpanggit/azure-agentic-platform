# terraform/modules

Reusable Terraform child modules, one per platform concern. Each module is called by the environment root modules with environment-specific inputs.

## Contents

| Module | Description |
|--------|-------------|
| `networking/` | VNet, subnets, private DNS zones |
| `compute-env/` | Container Apps Environment |
| `agent-apps/` | Container Apps for each domain agent |
| `foundry/` | Azure AI Foundry account, project, model deployments, capability hosts |
| `databases/` | Cosmos DB account + databases, PostgreSQL Flexible Server + pgvector |
| `eventhub/` | Event Hubs namespace and hubs for the detection plane |
| `fabric/` | Fabric workspace, Eventhouse, Activator (via `azapi`) |
| `keyvault/` | Key Vault with RBAC access policies |
| `monitoring/` | Application Insights, Log Analytics Workspace |
| `private-endpoints/` | Private endpoints for all PaaS resources |
| `rbac/` | Role assignments for managed identities |
| `entra-apps/` | Entra app registrations and service principals |
| `teams-bot/` | Teams bot registration and Container App |
| `azure-mcp-server/` | Azure MCP Server Container App (internal ingress) |
| `arc-mcp-server/` | Custom Arc MCP Server Container App (internal ingress) |
| `notifications/` | Alert action groups and notification rules |
| `activity-log/` | Azure Activity Log diagnostic settings |
| `github-runner/` | Self-hosted GitHub Actions runner Container App |
