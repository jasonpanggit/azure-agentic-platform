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

# Entra app registration management — DEFERRED.
# The aap-web-ui-prod app registration exists and works; Terraform does not need to own it today.
# Enabling this requires a Global Administrator to grant Application.ReadWrite.All to the CI SP.
# See docs/BOOTSTRAP.md Step 1 for the full procedure when ready to enable.
enable_entra_apps = false

# Web UI public URL — used by entra-apps module for redirect URI and CORS configuration
web_ui_public_url = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

# Azure MCP Server URL — set to the Container App / external URL where @azure/mcp runs
# Example: https://ca-azure-mcp-server-prod.<env>.azurecontainerapps.io
# azure_mcp_server_url = ""
