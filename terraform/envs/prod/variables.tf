variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant ID"
  type        = string
}

variable "client_id" {
  description = "Service principal client ID (app ID)"
  type        = string
  sensitive   = true
}

variable "client_secret" {
  description = "Service principal client secret"
  type        = string
  sensitive   = true
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus2"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "postgres_admin_password" {
  description = "Administrator password for PostgreSQL"
  type        = string
  sensitive   = true
}

variable "compute_subscription_id" {
  description = "Subscription ID for compute resources (may differ from platform in prod)"
  type        = string
  default     = ""
}

variable "network_subscription_id" {
  description = "Subscription ID for network resources (may differ from platform in prod)"
  type        = string
  default     = ""
}

variable "storage_subscription_id" {
  description = "Subscription ID for storage resources (may differ from platform in prod)"
  type        = string
  default     = ""
}

variable "all_subscription_ids" {
  description = "All in-scope subscription IDs for cross-subscription reader roles"
  type        = list(string)
  default     = []
}

variable "gateway_app_client_id" {
  description = "API gateway Entra app registration client ID for Fabric SP role assignment"
  type        = string
  default     = ""
}

variable "gateway_incidents_write_role_id" {
  description = "incidents.write app role ID on the gateway app registration"
  type        = string
  default     = ""
}

variable "fabric_admin_email" {
  description = "Email address of the Fabric capacity administrator"
  type        = string
}

variable "cors_allowed_origins" {
  description = "CORS allowed origins for api-gateway in prod"
  type        = string
  default     = "*"
}

# Teams Bot configuration
variable "teams_bot_id" {
  description = "Azure AD app registration client ID for the Teams bot (BOT_ID). Set after bot registration is created."
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

variable "web_ui_public_url" {
  description = "Public URL of the web UI for deep links in Teams Adaptive Cards"
  type        = string
  default     = ""
}

variable "teams_channel_id" {
  description = "Default Teams channel ID for proactive card posting"
  type        = string
  default     = ""
}

variable "orchestrator_agent_id" {
  description = "Foundry Agent ID for the Orchestrator agent (created in Azure AI Foundry portal). Required for chat and incident dispatch."
  type        = string
  default     = ""
}

variable "compute_agent_id" {
  type    = string
  default = ""
}

variable "network_agent_id" {
  type    = string
  default = ""
}

variable "storage_agent_id" {
  type    = string
  default = ""
}

variable "security_agent_id" {
  type    = string
  default = ""
}

variable "sre_agent_id" {
  type    = string
  default = ""
}

variable "arc_agent_id" {
  type    = string
  default = ""
}

variable "patch_agent_id" {
  type    = string
  default = ""
}

variable "eol_agent_id" {
  description = "Foundry Agent ID for the EOL domain agent"
  type        = string
  default     = ""
}

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

variable "enable_entra_apps" {
  description = "Enable Entra ID app registration management. Requires the Terraform SP to have Microsoft Graph Application.ReadWrite.All permission. Set false to skip Entra resources when the SP lacks Graph API permissions."
  type        = bool
  default     = false
}

variable "enable_teams_bot" {
  description = "Enable Teams Bot module (creates Azure Bot resource + Entra app registration). Requires Microsoft Graph Application.ReadWrite.All on the Terraform SP and import blocks for the existing aap-teams-bot-prod bot resource."
  type        = bool
  default     = false
}

variable "postgres_dsn" {
  description = "PostgreSQL DSN for agents that need direct DB access (e.g., eol-agent eol_cache table)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "pgvector_connection_string" {
  description = "PostgreSQL connection string for runbook RAG on api-gateway (PGVECTOR_CONNECTION_STRING). Format: postgresql://user:pass@host:5432/db?sslmode=require"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_mcp_image_tag" {
  description = "Docker image tag for the Azure MCP Server Container App (services/azure-mcp-server)"
  type        = string
  default     = "latest"
}

variable "api_gateway_auth_mode" {
  description = "Auth mode for API gateway: 'entra' (production) or 'disabled' (local dev only). Defaults to 'entra' (fail-closed)."
  type        = string
  default     = "entra"
}

variable "api_gateway_client_id" {
  description = "Entra app registration client ID for API gateway Entra auth (API_GATEWAY_CLIENT_ID)."
  type        = string
  default     = ""
}

variable "api_gateway_tenant_id" {
  description = "Entra tenant ID for API gateway Entra auth (API_GATEWAY_TENANT_ID)."
  type        = string
  default     = ""
}

variable "github_pat" {
  description = "Fine-grained GitHub PAT for the self-hosted runner. Required permissions: Actions=read, Administration=read+write on the azure-agentic-platform repository. Set via TF_VAR_github_pat or credentials.tfvars."
  type        = string
  sensitive   = true
  default     = ""
}
