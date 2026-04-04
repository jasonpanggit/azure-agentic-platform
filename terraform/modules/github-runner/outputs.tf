output "container_app_job_name" {
  description = "Name of the Container App Job for the GitHub Actions runner"
  value       = azurerm_container_app_job.github_runner.name
}

output "runner_identity_id" {
  description = "Resource ID of the runner managed identity"
  value       = azurerm_user_assigned_identity.runner.id
}

output "runner_identity_client_id" {
  description = "Client ID of the runner managed identity (for OIDC workflows)"
  value       = azurerm_user_assigned_identity.runner.client_id
}

output "runner_identity_principal_id" {
  description = "Principal ID of the runner managed identity (for RBAC)"
  value       = azurerm_user_assigned_identity.runner.principal_id
}
