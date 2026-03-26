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

variable "vnet_address_space" {
  description = "Address space for the VNet"
  type        = list(string)
  default     = ["10.0.0.0/16"]
}

variable "subnet_container_apps_cidr" {
  description = "CIDR for the Container Apps subnet"
  type        = string
  default     = "10.0.0.0/23"
}

variable "subnet_private_endpoints_cidr" {
  description = "CIDR for the private endpoints subnet"
  type        = string
  default     = "10.0.2.0/24"
}

variable "subnet_postgres_cidr" {
  description = "CIDR for the PostgreSQL delegated subnet"
  type        = string
  default     = "10.0.3.0/24"
}

variable "subnet_foundry_cidr" {
  description = "CIDR for the Foundry private endpoint subnet (reserved)"
  type        = string
  default     = "10.0.4.0/24"
}

variable "subnet_reserved_1_cidr" {
  description = "CIDR for reserved subnet (Phase 4 Event Hub networking)"
  type        = string
  default     = "10.0.64.0/24"
}
