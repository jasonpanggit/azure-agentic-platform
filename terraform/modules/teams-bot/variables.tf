variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "required_tags" {
  description = "Required tags for all resources"
  type        = map(string)
}

variable "tenant_id" {
  description = "Entra tenant ID for SingleTenant bot"
  type        = string
}

variable "keyvault_id" {
  description = "Key Vault resource ID for storing bot credentials"
  type        = string
}

variable "teams_bot_fqdn" {
  description = "FQDN of the teams-bot Container App (for messaging endpoint)"
  type        = string
  default     = ""
}

variable "bot_sku" {
  description = "Azure Bot pricing tier (F0 = free, S1 = standard)"
  type        = string
  default     = "F0"
}
