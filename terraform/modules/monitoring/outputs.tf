output "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace"
  value       = azurerm_log_analytics_workspace.main.id
}

output "log_analytics_workspace_customer_id" {
  description = "Customer ID (GUID) of the Log Analytics workspace — used as LOG_ANALYTICS_WORKSPACE_ID for API queries"
  value       = azurerm_log_analytics_workspace.main.workspace_id
}

output "log_analytics_workspace_name" {
  description = "Name of the Log Analytics workspace"
  value       = azurerm_log_analytics_workspace.main.name
}

output "app_insights_id" {
  description = "Resource ID of Application Insights"
  value       = azurerm_application_insights.main.id
}

output "app_insights_connection_string" {
  description = "Connection string for Application Insights"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "app_insights_instrumentation_key" {
  description = "Instrumentation key for Application Insights (legacy)"
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}
