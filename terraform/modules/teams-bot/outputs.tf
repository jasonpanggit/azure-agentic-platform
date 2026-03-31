output "bot_id" {
  description = "Microsoft App ID (client_id) of the Teams bot app registration"
  value       = azuread_application.teams_bot.client_id
}

output "bot_password" {
  description = "Client secret for the Teams bot app registration"
  value       = azuread_application_password.teams_bot.value
  sensitive   = true
}

output "bot_service_id" {
  description = "Resource ID of the Azure Bot service"
  value       = azurerm_bot_service_azure_bot.main.id
}
