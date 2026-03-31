environment = "prod"
location    = "eastus2"

# Subscription and tenant IDs — set via environment variables or CI secrets:
#   TF_VAR_subscription_id = "..."
#   TF_VAR_tenant_id       = "..."
#   TF_VAR_postgres_admin_password = "..."

# Foundry agent IDs — provisioned via scripts/provision-domain-agents.py
# Committed here so terraform apply does not wipe manually-set env vars.
orchestrator_agent_id = "asst_NeBVjCA5isNrIERoGYzRpBTu"
