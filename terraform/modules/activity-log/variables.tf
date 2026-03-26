variable "subscription_ids" {
  description = "List of subscription IDs to export Activity Log from"
  type        = list(string)
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace for Activity Log export"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}
