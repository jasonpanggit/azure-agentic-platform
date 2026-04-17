variable "agent_principal_ids" {
  description = "Map of agent name to system-assigned managed identity principal ID (from agent-apps module)"
  type        = map(string)
}

variable "platform_subscription_id" {
  description = "Subscription ID for the AAP platform resources"
  type        = string
}

variable "compute_subscription_id" {
  description = "Subscription ID for compute resources (defaults to platform if not set)"
  type        = string
  default     = ""
}

variable "network_subscription_id" {
  description = "Subscription ID for network resources (defaults to platform if not set)"
  type        = string
  default     = ""
}

variable "storage_subscription_id" {
  description = "Subscription ID for storage resources (defaults to platform if not set)"
  type        = string
  default     = ""
}

variable "arc_resource_group_ids" {
  description = "List of resource group IDs containing Arc resources (empty in Phase 2; populate in Phase 3)"
  type        = list(string)
  default     = []
}

variable "all_subscription_ids" {
  description = "List of all in-scope subscription IDs for cross-subscription reader roles (storage, security, SRE)"
  type        = list(string)
}

variable "acr_id" {
  description = "Resource ID of the Azure Container Registry for AcrPull role assignments"
  type        = string
  default     = ""
}

variable "resource_group_name" {
  description = "Resource group name containing the Foundry account (used for Azure AI Developer scope)"
  type        = string
  default     = ""
}

variable "foundry_account_name" {
  description = "Name of the Azure AI Foundry (Cognitive Services) account (used for Azure AI Developer scope)"
  type        = string
  default     = ""
}

variable "key_vault_id" {
  description = "Resource ID of the Key Vault for api-gateway Key Vault Secrets User role assignment"
  type        = string
  default     = ""
}
