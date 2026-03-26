variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "required_tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
}

variable "container_apps_environment_id" {
  description = "Resource ID of the Container Apps environment (from compute-env module)"
  type        = string
}

variable "acr_login_server" {
  description = "ACR login server URL (from compute-env module)"
  type        = string
}

variable "foundry_account_endpoint" {
  description = "Foundry account endpoint URL (from foundry module)"
  type        = string
}

variable "foundry_project_id" {
  description = "Foundry project resource ID (from foundry module)"
  type        = string
}

variable "foundry_model_deployment_name" {
  description = "gpt-4o model deployment name (from foundry module)"
  type        = string
}

variable "app_insights_connection_string" {
  description = "Application Insights connection string (from monitoring module)"
  type        = string
  sensitive   = true
}

variable "cosmos_endpoint" {
  description = "Cosmos DB endpoint URL (from databases module)"
  type        = string
}

variable "cosmos_database_name" {
  description = "Cosmos DB database name (from databases module)"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag for agent containers"
  type        = string
  default     = "latest"
}
