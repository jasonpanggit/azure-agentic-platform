variable "resource_group_name" {
  description = "Name of the resource group where the Arc MCP Server Container App is deployed"
  type        = string
}

variable "location" {
  description = "Azure region for the Container App"
  type        = string
}

variable "environment" {
  description = "Deployment environment name (dev, staging, prod)"
  type        = string
}

variable "container_apps_environment_id" {
  description = "Resource ID of the Container Apps environment (from compute-env module)"
  type        = string
}

variable "container_apps_env_domain" {
  description = "Default domain of the Container Apps environment for internal FQDN construction"
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

variable "app_insights_connection_string" {
  description = "Application Insights connection string for OpenTelemetry"
  type        = string
  sensitive   = true
}

variable "arc_subscription_ids" {
  description = "List of subscription IDs containing Arc resources; Reader role is granted on each"
  type        = list(string)
}

variable "arc_disconnect_alert_hours" {
  description = "Hours after which a disconnected Arc server is flagged as prolonged disconnection (MONITOR-004)"
  type        = number
  default     = 1
}

variable "required_tags" {
  description = "Tags applied to all resources in this module"
  type        = map(string)
  default     = {}
}

variable "use_placeholder_image" {
  description = "Use a public placeholder image for initial provisioning (avoids ACR auth chicken-and-egg). CI/CD deploys the real image after AcrPull role is assigned."
  type        = bool
  default     = false
}
