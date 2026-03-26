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

# Subnet for all private endpoints
variable "private_endpoint_subnet_id" {
  description = "Subnet ID for private endpoints"
  type        = string
}

# Target resource IDs
variable "cosmos_account_id" {
  description = "Resource ID of the Cosmos DB account"
  type        = string
}

variable "acr_id" {
  description = "Resource ID of the ACR"
  type        = string
}

variable "keyvault_id" {
  description = "Resource ID of the Key Vault"
  type        = string
}

variable "foundry_account_id" {
  description = "Resource ID of the Foundry/AI Services account"
  type        = string
}

# Private DNS zone IDs
variable "private_dns_zone_cosmos_id" {
  description = "Private DNS zone ID for Cosmos DB"
  type        = string
}

variable "private_dns_zone_acr_id" {
  description = "Private DNS zone ID for ACR"
  type        = string
}

variable "private_dns_zone_keyvault_id" {
  description = "Private DNS zone ID for Key Vault"
  type        = string
}

variable "private_dns_zone_cognitive_id" {
  description = "Private DNS zone ID for Cognitive Services (Foundry)"
  type        = string
}
