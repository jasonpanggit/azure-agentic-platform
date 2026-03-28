output "foundry_account_id" {
  description = "Resource ID of the Foundry (AI Services) account"
  value       = azurerm_cognitive_account.foundry.id
}

output "foundry_account_endpoint" {
  description = "Endpoint URL of the Foundry account"
  value       = azurerm_cognitive_account.foundry.endpoint
}

output "foundry_account_name" {
  description = "Name of the Foundry account"
  value       = azurerm_cognitive_account.foundry.name
}

output "foundry_project_id" {
  description = "Resource ID of the Foundry project"
  value       = azurerm_cognitive_account_project.main.id
}

output "foundry_project_endpoint" {
  description = "AI Foundry API endpoint for the project (required by AgentsClient)"
  value       = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.services.ai.azure.com/api/projects/${azurerm_cognitive_account_project.main.name}"
}

output "foundry_model_deployment_name" {
  description = "Name of the gpt-4o model deployment"
  value       = azurerm_cognitive_deployment.gpt4o.name
}

output "foundry_principal_id" {
  description = "Principal ID of the Foundry account system-assigned identity"
  value       = azurerm_cognitive_account.foundry.identity[0].principal_id
}
