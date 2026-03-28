output "web_ui_client_id" {
  description = "Client ID (appId) of the web UI Entra app registration"
  value       = azuread_application.web_ui.client_id
}
