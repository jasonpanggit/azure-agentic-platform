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
  default     = "dev"
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
