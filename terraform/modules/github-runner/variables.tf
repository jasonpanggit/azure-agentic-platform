variable "resource_group_name" {
  description = "Resource group for the runner resources"
  type        = string
}

variable "location" {
  description = "Azure region"
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
  description = "ID of the Container Apps Environment to deploy the runner job into"
  type        = string
}

variable "acr_id" {
  description = "Resource ID of the Azure Container Registry"
  type        = string
}

variable "acr_login_server" {
  description = "Login server hostname of the Azure Container Registry"
  type        = string
}

variable "github_pat" {
  description = "Fine-grained GitHub PAT with Actions=read, Administration=read+write"
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub organisation or username (e.g. 'jasonpanggit')"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (e.g. 'azure-agentic-platform')"
  type        = string
}

variable "runner_image_tag" {
  description = "Tag of the github-runner image in ACR"
  type        = string
  default     = "latest"
}

variable "max_runners" {
  description = "Maximum number of concurrent runner replicas"
  type        = number
  default     = 10
}

variable "runner_cpu" {
  description = "CPU allocated per runner replica (cores)"
  type        = number
  default     = 2.0
}

variable "runner_memory" {
  description = "Memory allocated per runner replica"
  type        = string
  default     = "4Gi"
}

variable "runner_labels" {
  description = "Comma-separated runner labels for runs-on targeting (e.g. 'self-hosted,azure,linux')"
  type        = string
  default     = "self-hosted,azure,linux"
}

variable "replica_timeout_seconds" {
  description = "Maximum seconds a runner replica may run before being killed"
  type        = number
  default     = 1800
}
