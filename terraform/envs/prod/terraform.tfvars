environment = "prod"
location    = "eastus2"

# Subscription and tenant IDs — set via environment variables or CI secrets:
#   TF_VAR_subscription_id = "..."
#   TF_VAR_tenant_id       = "..."
#   TF_VAR_postgres_admin_password = "..."

# Foundry agent IDs — provisioned via scripts/provision-domain-agents.py
# Committed here so terraform apply does not wipe manually-set env vars.
orchestrator_agent_id = "asst_NeBVjCA5isNrIERoGYzRpBTu"

cors_allowed_origins = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
all_subscription_ids = ["4c727b88-12f4-4c91-9c2b-372aab3bbae9"]

# Entra app registration management.
# BLOCKED: CI SP (65cf695c-1def-48ba-96af-d968218c90ba) needs Application.ReadWrite.All
# admin-consented on the Entra tenant before this can be enabled.
# To enable:
#   1. Run: az ad app permission admin-consent --id 65cf695c-1def-48ba-96af-d968218c90ba
#   2. Set enable_entra_apps = true (below)
#   3. Uncomment the import blocks in imports.tf
#   4. Run: terraform apply -var-file="credentials.tfvars"
#   See docs/BOOTSTRAP.md Step 1 for the full grant procedure.
enable_entra_apps = false

# Web UI public URL — used by entra-apps module for redirect URI and CORS configuration
web_ui_public_url = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
