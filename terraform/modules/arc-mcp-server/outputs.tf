output "arc_mcp_server_id" {
  description = "Resource ID of the Arc MCP Server Container App"
  value       = azurerm_container_app.arc_mcp_server.id
}

output "arc_mcp_server_principal_id" {
  description = "System-assigned managed identity principal ID of the Arc MCP Server"
  value       = azurerm_container_app.arc_mcp_server.identity[0].principal_id
}

output "arc_mcp_server_fqdn" {
  description = "Internal FQDN of the Arc MCP Server (for ARC_MCP_SERVER_URL env var)"
  value       = azurerm_container_app.arc_mcp_server.ingress[0].fqdn
}

output "internal_fqdn" {
  description = "Internal FQDN for Arc MCP Server (Foundry MCP connection target — internal ingress only)"
  value       = azurerm_container_app.arc_mcp_server.ingress[0].fqdn
}

output "arc_mcp_server_url" {
  description = "Full internal URL for Arc Agent to call Arc MCP Server tools"
  value       = "http://${azurerm_container_app.arc_mcp_server.ingress[0].fqdn}/mcp"
}
