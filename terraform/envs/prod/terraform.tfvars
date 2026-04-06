environment = "prod"
location    = "eastus2"

# Subscription and tenant IDs — set via environment variables or CI secrets:
#   TF_VAR_subscription_id = "..."
#   TF_VAR_tenant_id       = "..."
#   TF_VAR_postgres_admin_password = "..."

# Foundry agent IDs — provisioned via scripts/provision-domain-agents.py
# Committed here so terraform apply does not wipe manually-set env vars.
# IDs match the live Foundry orchestrator connected-agent tools (260331-ize wiring).
orchestrator_agent_id = "asst_NeBVjCA5isNrIERoGYzRpBTu"
compute_agent_id      = "asst_rPDw83BXGrmNDE73xMy6IFE5"
network_agent_id      = "asst_ynlfwck70rb2olLGohZSWoKz"
storage_agent_id      = "asst_BDm56ofymsrQnbdvutNmP7fI"
security_agent_id     = "asst_bHgDk44qPDLoqqMsln4GjPoK"
sre_agent_id          = "asst_4JoNlqMcQC3WPq9cTpowFfPe"
arc_agent_id          = "asst_YFobGKxsDGo9j1oIrimzWyfL"
patch_agent_id        = "asst_AEFTnaxXKMpOUCmjiLWhzlsW"
eol_agent_id          = "asst_hUNs2ASp1WsrMvGvuwA5T495"

cors_allowed_origins = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
all_subscription_ids = ["4c727b88-12f4-4c91-9c2b-372aab3bbae9"]

# Entra app registration management — DEFERRED.
# The aap-web-ui-prod app registration exists and works; Terraform does not need to own it today.
# Enabling this requires a Global Administrator to grant Application.ReadWrite.All to the CI SP.
# See docs/BOOTSTRAP.md Step 1 for the full procedure when ready to enable.
enable_entra_apps = true
enable_teams_bot  = true

# Fabric capacity administrator email (required for Fabric module)
# This is the email of the Entra user who administers the Fabric capacity.
# Set via: TF_VAR_fabric_admin_email="admin@yourdomain.com"
# fabric_admin_email = ""  # Set via TF_VAR_fabric_admin_email or credentials.tfvars

# Web UI public URL — used by entra-apps module for redirect URI and CORS configuration
web_ui_public_url = "https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

# Azure MCP Server — managed by Terraform module (module.azure_mcp_server).
# internal_fqdn is wired automatically into agent_apps.azure_mcp_server_url.
# image_tag below controls which ACR image to deploy.
azure_mcp_image_tag = "latest"

# API Gateway Entra authentication (SEC-003 / PROD-001)
# Enables Entra token validation on all non-health API endpoints.
# client_id matches NEXT_PUBLIC_AZURE_CLIENT_ID in the web-ui (aap-web-ui-prod app registration).
# tenant_id is the single Entra tenant for this platform.
# api_gateway_auth_mode is intentionally omitted here — controlled via the
# API_GATEWAY_AUTH_MODE GitHub Actions environment variable (TF_VAR_api_gateway_auth_mode).
# Defaults to "entra" when the GH variable is not set (see variables.tf).
api_gateway_client_id = "505df1d3-3bd3-4151-ae87-6e5974b72a44"
api_gateway_tenant_id = "abbdca26-d233-4a1e-9d8c-c4eebbc16e50"

# Teams channel ID for proactive alert delivery (PROD-005 / F-04)
# Set after installing the bot in the target channel.
# Retrieve via: bash scripts/ops/19-5-package-manifest.sh (shows instructions)
# or: az containerapp logs show --name ca-teams-bot-prod --resource-group rg-aap-prod --tail 50
# Once set, run: terraform apply -var-file=credentials.tfvars -target=module.agent_apps
teams_channel_id = ""

# PostgreSQL pgvector connection string for runbook RAG (BUG-002 / F-02 fix — Plan 19-4)
# The actual value with the admin password is in credentials.tfvars (not committed to git).
# Format: postgresql://aap_admin:<password>@aap-postgres-prod.postgres.database.azure.com:5432/aap?sslmode=require
# To set: bash scripts/ops/19-4-seed-runbooks.sh  (also seeds the 60 runbooks)
# See: docs/ops/runbook-seeding.md for full procedure
pgvector_connection_string = ""
