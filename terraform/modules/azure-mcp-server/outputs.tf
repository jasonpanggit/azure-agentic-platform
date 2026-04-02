output "container_app_id" {
  description = "Resource ID of the Azure MCP Server Container App"
  value       = azurerm_container_app.azure_mcp_server.id
}

output "internal_fqdn" {
  description = "Internal FQDN for Foundry MCP connection (internal ingress only)"
  value       = azurerm_container_app.azure_mcp_server.ingress[0].fqdn
}

output "principal_id" {
  description = "System-assigned managed identity principal ID of the Azure MCP Server"
  value       = azurerm_container_app.azure_mcp_server.identity[0].principal_id
}
