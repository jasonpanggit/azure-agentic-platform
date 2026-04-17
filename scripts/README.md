# scripts

Operational, provisioning, and development utility scripts for the Azure Agentic Platform. Not part of the application runtime — used to bootstrap, configure, and maintain the platform.

## Contents

- `ops/` — phase-specific operational scripts (MCP registration, detection plane activation, load tests)
- `seed-runbooks/` — seeds the PostgreSQL runbook library used by agent RAG
- `simulate-incidents/` — fires synthetic incidents against the API gateway for integration testing
- `bootstrap-state.sh` — creates the Terraform backend storage account
- `bootstrap-github-secrets.sh` — populates GitHub Actions secrets from Key Vault
- `provision-foundry-agents.py` — provisions Foundry Hosted Agents via `azure-ai-projects`
- `provision-domain-agents.py` — registers domain agents with the orchestrator
- `wire-domain-agents.py` — wires connected-agent handoffs in Foundry
- `configure-orchestrator.py` — updates orchestrator system prompt with live agent IDs
- `update-domain-agent-prompts.py` — syncs agent prompts from `sops/` to Foundry
- `upload_sops.py` — uploads SOPs to the runbook store
- `register_agents.py` — registers agents in Cosmos DB session store
- `grant-cosmos-rbac.sh` / `grant-state-rbac.sh` — assigns required RBAC roles
- `verify-arc-connectivity.sh` / `verify-managed-identity.sh` — connectivity health checks
- `seed-compliance-mappings.py` — seeds regulatory compliance mappings
- `lint_sops.py` — validates SOP markdown files against the schema
- `run-mock.sh` — starts a local mock agent server for development
