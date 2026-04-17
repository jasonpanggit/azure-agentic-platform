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

variable "model_name" {
  description = "Name of the model to deploy"
  type        = string
  default     = "gpt-4o"
}

variable "model_version" {
  description = "Version of the model to deploy"
  type        = string
  default     = "2024-11-20"
}

variable "model_capacity" {
  description = "Model deployment capacity in thousands of tokens per minute"
  type        = number
  default     = 10
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace for diagnostic settings"
  type        = string
}

variable "storage_account_name" {
  description = "Name of the Storage Account used for Foundry Agent Service thread storage"
  type        = string
}

variable "storage_account_id" {
  description = "Resource ID of the Storage Account used for Foundry Agent Service thread storage"
  type        = string
}
