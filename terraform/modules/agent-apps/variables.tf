variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "required_tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
}

variable "container_apps_environment_id" {
  description = "Resource ID of the Container Apps environment (from compute-env module)"
  type        = string
}

variable "acr_login_server" {
  description = "ACR login server URL (from compute-env module)"
  type        = string
}

variable "foundry_account_endpoint" {
  description = "Foundry account endpoint URL (from foundry module)"
  type        = string
}

variable "foundry_project_endpoint" {
  description = "AI Foundry API project endpoint URL required by AgentsClient (from foundry module)"
  type        = string
}

variable "foundry_project_id" {
  description = "Foundry project resource ID (from foundry module)"
  type        = string
}

variable "foundry_model_deployment_name" {
  description = "gpt-4o model deployment name (from foundry module)"
  type        = string
}

variable "app_insights_connection_string" {
  description = "Application Insights connection string (from monitoring module)"
  type        = string
  sensitive   = true
}

variable "cosmos_endpoint" {
  description = "Cosmos DB endpoint URL (from databases module)"
  type        = string
}

variable "cosmos_database_name" {
  description = "Cosmos DB database name (from databases module)"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag for agent containers"
  type        = string
  default     = "latest"
}

variable "use_placeholder_image" {
  description = "Use a public placeholder image instead of ACR images. Set true for initial infra provisioning before any images are built; CI/CD sets this to false once images exist."
  type        = bool
  default     = true
}

variable "cors_allowed_origins" {
  description = "Comma-separated CORS allowed origins for the api-gateway (D-15)"
  type        = string
  default     = "*"
}

variable "orchestrator_agent_id" {
  description = "Foundry Agent ID for the Orchestrator agent (created in Azure AI Foundry portal, format: asst_xxx). Required for chat and incident dispatch."
  type        = string
  default     = ""
}

variable "compute_agent_id" {
  description = "Foundry Agent ID for the Compute domain agent"
  type        = string
  default     = ""
}

variable "network_agent_id" {
  description = "Foundry Agent ID for the Network domain agent"
  type        = string
  default     = ""
}

variable "storage_agent_id" {
  description = "Foundry Agent ID for the Storage domain agent"
  type        = string
  default     = ""
}

variable "security_agent_id" {
  description = "Foundry Agent ID for the Security domain agent"
  type        = string
  default     = ""
}

variable "sre_agent_id" {
  description = "Foundry Agent ID for the SRE domain agent"
  type        = string
  default     = ""
}

variable "arc_agent_id" {
  description = "Foundry Agent ID for the Arc domain agent"
  type        = string
  default     = ""
}

variable "patch_agent_id" {
  description = "Foundry Agent ID for the Patch domain agent"
  type        = string
  default     = ""
}

variable "arc_mcp_server_url" {
  description = "Internal URL of the Arc MCP Server Container App (e.g. http://ca-arc-mcp-server-prod.internal/mcp)"
  type        = string
  default     = ""
}

variable "azure_mcp_server_url" {
  description = "Public or internal URL of the Azure MCP Server (npx @azure/mcp@latest) for patch and EOL agents (AZURE_MCP_SERVER_URL)"
  type        = string
  default     = ""
}

# Teams Bot specific variables
variable "teams_bot_id" {
  description = "Azure AD app registration client ID for the Teams bot (BOT_ID)"
  type        = string
  default     = ""
}

variable "teams_bot_password" {
  description = "Azure AD app registration client secret for the Teams bot (BOT_PASSWORD)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "teams_bot_tenant_id" {
  description = "Entra tenant ID for SingleTenant bot authentication (BOT_TENANT_ID)"
  type        = string
  default     = ""
}

variable "api_gateway_internal_url" {
  description = "Internal URL for the api-gateway service used by the teams-bot (API_GATEWAY_INTERNAL_URL)"
  type        = string
  default     = ""
}

variable "web_ui_public_url" {
  description = "Public URL of the web UI for deep links in Adaptive Cards (WEB_UI_PUBLIC_URL)"
  type        = string
  default     = ""
}

variable "teams_channel_id" {
  description = "Default Teams channel ID for proactive card posting (TEAMS_CHANNEL_ID)"
  type        = string
  default     = ""
}

variable "log_analytics_workspace_customer_id" {
  description = "Log Analytics workspace customer ID (GUID) for the web-ui Observability tab"
  type        = string
  default     = ""
}

variable "eol_agent_id" {
  description = "Foundry Agent ID for the EOL domain agent"
  type        = string
  default     = ""
}

variable "postgres_dsn" {
  description = "PostgreSQL DSN for agents that need direct DB access (e.g., eol-agent eol_cache)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "pgvector_connection_string" {
  description = "PostgreSQL connection string for pgvector runbook RAG (api-gateway PGVECTOR_CONNECTION_STRING). Format: postgresql://user:pass@host:5432/db?sslmode=require"
  type        = string
  sensitive   = true
  default     = ""
}

variable "api_gateway_auth_mode" {
  description = "Auth mode for API gateway: 'entra' (production) or 'disabled' (local dev only). Defaults to 'entra' (fail-closed)."
  type        = string
  default     = "entra"
}

variable "api_gateway_client_id" {
  description = "Entra app registration client ID for API gateway Entra auth (API_GATEWAY_CLIENT_ID). Must match NEXT_PUBLIC_AZURE_CLIENT_ID in web-ui."
  type        = string
  default     = ""
}

variable "api_gateway_tenant_id" {
  description = "Entra tenant ID for API gateway Entra auth (API_GATEWAY_TENANT_ID)."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Phase 29: A2A connection endpoints — internal HTTPS URLs for domain agents
# Used by azapi_resource.a2a_connection to register A2A connections in Foundry.
# Default empty string = connection resource skipped (no-op in dev).
# ---------------------------------------------------------------------------

variable "orchestrator_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Orchestrator agent Container App (health checks)"
  type        = string
  default     = ""
}

variable "compute_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Compute agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "arc_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Arc agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "eol_agent_endpoint" {
  description = "Internal HTTPS endpoint for the EOL agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "network_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Network agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "patch_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Patch agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "security_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Security agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "sre_agent_endpoint" {
  description = "Internal HTTPS endpoint for the SRE agent Container App (A2A)"
  type        = string
  default     = ""
}

variable "storage_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Storage agent Container App (A2A)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Phase 30: SOP Engine — vector store ID + notification env vars
# ---------------------------------------------------------------------------

variable "sop_vector_store_id" {
  description = "Foundry vector store ID for SOP files (set after running upload_sops.py)"
  type        = string
  default     = ""
}

variable "notification_email_from" {
  description = "Sender email address for ACS email notifications (SOP engine)"
  type        = string
  default     = ""
}

variable "notification_email_to" {
  description = "Default recipient email address for ACS email notifications (SOP engine)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Phase 43: Centralized Logging — ARM resource ID for the Log Analytics
# workspace used by the api-gateway's Enable Logging (DCR) endpoints.
# Distinct from log_analytics_workspace_customer_id (GUID) — the ARM ID is
# required to create Data Collection Rules targeting the workspace.
# ---------------------------------------------------------------------------

variable "log_analytics_workspace_resource_id" {
  description = "ARM resource ID of the Log Analytics workspace used by api-gateway diagnostic settings (LOG_ANALYTICS_WORKSPACE_RESOURCE_ID). Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.OperationalInsights/workspaces/{name}"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Phase 49: Messaging Agent — Foundry agent ID and A2A endpoint
# ---------------------------------------------------------------------------

variable "messaging_agent_id" {
  description = "Foundry Agent ID for the Messaging domain agent (Service Bus + Event Hub)"
  type        = string
  default     = ""
}

variable "messaging_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Messaging agent Container App (A2A)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Phase 52: FinOps Agent — Foundry agent ID and A2A endpoint
# ---------------------------------------------------------------------------

variable "finops_agent_id" {
  description = "Foundry Agent ID for the FinOps domain agent (Cost Management)"
  type        = string
  default     = ""
}

variable "finops_agent_endpoint" {
  description = "FinOps agent A2A endpoint URL (set after provisioning Foundry agent)"
  type        = string
  default     = ""
}

variable "key_vault_url" {
  description = "Azure Key Vault URI injected into api-gateway as KEY_VAULT_URL for SPN credential store"
  type        = string
  default     = ""
}
