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

variable "container_apps_subnet_id" {
  description = "Subnet ID for the Container Apps environment"
  type        = string
}

variable "acr_agent_pool_subnet_id" {
  description = "Subnet ID for the ACR Tasks private agent pool"
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace"
  type        = string
}
