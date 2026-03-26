# --- Resource Group ---
output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "resource_group_id" {
  value = azurerm_resource_group.main.id
}

# --- Networking ---
output "vnet_id" {
  value = module.networking.vnet_id
}

output "container_apps_subnet_id" {
  value = module.networking.subnet_container_apps_id
}

# --- Monitoring ---
output "log_analytics_workspace_id" {
  value = module.monitoring.log_analytics_workspace_id
}

output "app_insights_connection_string" {
  value     = module.monitoring.app_insights_connection_string
  sensitive = true
}

# --- Foundry ---
output "foundry_account_id" {
  value = module.foundry.foundry_account_id
}

output "foundry_account_endpoint" {
  value = module.foundry.foundry_account_endpoint
}

output "foundry_project_id" {
  value = module.foundry.foundry_project_id
}

output "foundry_model_deployment_name" {
  value = module.foundry.foundry_model_deployment_name
}

# --- Databases ---
output "cosmos_account_id" {
  value = module.databases.cosmos_account_id
}

output "cosmos_endpoint" {
  value = module.databases.cosmos_endpoint
}

output "cosmos_database_name" {
  value = module.databases.cosmos_database_name
}

output "postgres_server_id" {
  value = module.databases.postgres_server_id
}

output "postgres_fqdn" {
  value = module.databases.postgres_fqdn
}

# --- Compute ---
output "container_apps_environment_id" {
  value = module.compute_env.container_apps_environment_id
}

output "container_apps_environment_default_domain" {
  value = module.compute_env.container_apps_environment_default_domain
}

output "acr_id" {
  value = module.compute_env.acr_id
}

output "acr_login_server" {
  value = module.compute_env.acr_login_server
}

# --- Key Vault ---
output "keyvault_id" {
  value = module.keyvault.keyvault_id
}

output "keyvault_uri" {
  value = module.keyvault.keyvault_uri
}

# --- Private Endpoints ---
output "cosmos_private_endpoint_id" {
  value = module.private_endpoints.cosmos_private_endpoint_id
}

output "acr_private_endpoint_id" {
  value = module.private_endpoints.acr_private_endpoint_id
}

# --- Agent Apps ---
output "agent_entra_ids" {
  description = "Agent Entra object IDs for Agent 365 discovery"
  value       = module.agent_apps.agent_entra_ids
}

output "api_gateway_url" {
  description = "API gateway URL"
  value       = module.agent_apps.api_gateway_url
}

output "rbac_assignment_count" {
  description = "Total RBAC assignments provisioned"
  value       = module.rbac.role_assignment_count
}
