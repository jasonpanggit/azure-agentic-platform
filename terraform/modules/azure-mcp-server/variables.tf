variable "environment" {
  description = "Deployment environment name (dev, staging, prod)"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group where the Azure MCP Server Container App is deployed"
  type        = string
}

variable "location" {
  description = "Azure region for the Container App"
  type        = string
}

variable "container_apps_environment_id" {
  description = "Resource ID of the Container Apps environment (from compute-env module)"
  type        = string
}

variable "acr_login_server" {
  description = "Login server of the Azure Container Registry"
  type        = string
}

variable "acr_id" {
  description = "Resource ID of the Azure Container Registry for AcrPull role assignment"
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "use_placeholder_image" {
  description = "Use a public placeholder image for initial provisioning (avoids ACR auth chicken-and-egg). CI/CD deploys the real image after AcrPull role is assigned."
  type        = bool
  default     = false
}

variable "subscription_id" {
  description = "Subscription ID to grant Reader role on for Azure MCP Server"
  type        = string
}

variable "app_insights_connection_string" {
  description = "Application Insights connection string for OpenTelemetry"
  type        = string
  sensitive   = true
}

variable "required_tags" {
  description = "Tags applied to all resources in this module"
  type        = map(string)
  default     = {}
}
