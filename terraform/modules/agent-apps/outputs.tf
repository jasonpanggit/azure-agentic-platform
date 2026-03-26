# NOTE (INFRA-005): Per D-17 in 02-CONTEXT.md, the system_assigned_principal_id from
# azurerm_container_app IS the Entra Agent ID — Azure registers it automatically when a
# Container App is created with SystemAssigned identity. No separate azapi_data_plane_resource
# block is required for the base identity. The principal_id values below serve as the Entra
# Agent ID object IDs for Phase 7 Agent 365 auto-discovery.

output "agent_principal_ids" {
  description = "Map of agent/service name to system-assigned managed identity principal ID"
  value = {
    for name, app in azurerm_container_app.agents :
    name => app.identity[0].principal_id
  }
}

output "agent_entra_ids" {
  description = "Map of agent name to Entra object ID (principal_id) for Agent 365 auto-discovery — excludes api-gateway"
  value = {
    for name, app in azurerm_container_app.agents :
    name => app.identity[0].principal_id
    if name != "api-gateway"
  }
}

output "api_gateway_fqdn" {
  description = "FQDN of the API gateway Container App"
  value       = azurerm_container_app.agents["api-gateway"].ingress[0].fqdn
}

output "api_gateway_url" {
  description = "Full HTTPS URL of the API gateway"
  value       = "https://${azurerm_container_app.agents["api-gateway"].ingress[0].fqdn}"
}

output "container_app_ids" {
  description = "Map of app name to Container App resource ID"
  value = {
    for name, app in azurerm_container_app.agents :
    name => app.id
  }
}
