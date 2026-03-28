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
