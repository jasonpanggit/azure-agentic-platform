environment = "staging"
location    = "eastus2"

# Subscription and tenant IDs — set via environment variables or CI secrets:
#   TF_VAR_subscription_id = "..."
#   TF_VAR_tenant_id       = "..."
#   TF_VAR_postgres_admin_password = "..."

# Azure MCP Server URL — set to the Container App / external URL where @azure/mcp runs
# Example: https://ca-azure-mcp-server-staging.<env>.azurecontainerapps.io
# azure_mcp_server_url = ""

# API Gateway Entra authentication — staging uses entra mode for pre-prod validation.
# Validates the full auth chain before applying to prod (Plan 19-2 Task 8).
# Set to "disabled" locally or to skip auth during infra-only deploys.
api_gateway_auth_mode = "entra"
api_gateway_client_id = "505df1d3-3bd3-4151-ae87-6e5974b72a44"
api_gateway_tenant_id = "abbdca26-d233-4a1e-9d8c-c4eebbc16e50"
