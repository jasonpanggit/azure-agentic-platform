variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "required_tags" {
  description = "Required tags for all resources"
  type        = map(string)

  validation {
    condition = alltrue([
      contains(keys(var.required_tags), "environment"),
      contains(keys(var.required_tags), "managed-by"),
      contains(keys(var.required_tags), "project"),
      var.required_tags["managed-by"] == "terraform",
      var.required_tags["project"] == "aap",
    ])
    error_message = "Tags must include 'environment', 'managed-by: terraform', and 'project: aap'."
  }
}

# Cosmos DB variables
variable "cosmos_serverless" {
  description = "Use Serverless capacity mode (true for dev/staging, false for prod)"
  type        = bool
  default     = true
}

variable "cosmos_secondary_location" {
  description = "Secondary region for Cosmos DB multi-region (prod only, ignored if serverless)"
  type        = string
  default     = ""
}

variable "cosmos_max_throughput" {
  description = "Max autoscale throughput in RU/s (prod only, ignored if serverless)"
  type        = number
  default     = 4000
}

# PostgreSQL variables
variable "postgres_subnet_id" {
  description = "Subnet ID for PostgreSQL VNet injection (delegated subnet)"
  type        = string
}

variable "postgres_dns_zone_id" {
  description = "Private DNS zone ID for PostgreSQL"
  type        = string
}

variable "postgres_sku" {
  description = "SKU for PostgreSQL Flexible Server"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "Storage in MB for PostgreSQL Flexible Server"
  type        = number
  default     = 32768
}

variable "postgres_admin_login" {
  description = "Administrator login for PostgreSQL"
  type        = string
  default     = "aap_admin"
}

variable "postgres_admin_password" {
  description = "Administrator password for PostgreSQL"
  type        = string
  sensitive   = true
}

variable "tenant_id" {
  description = "Entra tenant ID for PostgreSQL Entra auth"
  type        = string
}

variable "agent_principal_ids" {
  description = "Map of agent name to managed identity principal ID for Cosmos data-plane RBAC"
  type        = map(string)
  default     = {}
}

variable "enable_postgres_entra_auth" {
  description = "Add Entra auth administrator for PostgreSQL (server already has active_directory_auth_enabled = true)"
  type        = bool
  default     = true
}

variable "api_gateway_principal_id" {
  description = "Managed identity principal ID of the API gateway for PostgreSQL Entra auth"
  type        = string
  default     = ""
}
