variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant ID"
  type        = string
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus2"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "staging"
}

variable "postgres_admin_password" {
  description = "Administrator password for PostgreSQL"
  type        = string
  sensitive   = true
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
