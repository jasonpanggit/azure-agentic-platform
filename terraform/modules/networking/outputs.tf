output "vnet_id" {
  description = "Resource ID of the VNet"
  value       = azurerm_virtual_network.main.id
}

output "vnet_name" {
  description = "Name of the VNet"
  value       = azurerm_virtual_network.main.name
}

output "subnet_container_apps_id" {
  description = "Resource ID of the Container Apps subnet"
  value       = azurerm_subnet.container_apps.id
}

output "subnet_private_endpoints_id" {
  description = "Resource ID of the private endpoints subnet"
  value       = azurerm_subnet.private_endpoints.id
}

output "subnet_postgres_id" {
  description = "Resource ID of the PostgreSQL delegated subnet"
  value       = azurerm_subnet.postgres.id
}

output "subnet_foundry_id" {
  description = "Resource ID of the Foundry subnet (reserved)"
  value       = azurerm_subnet.foundry.id
}

output "nsg_foundry_id" {
  description = "Resource ID of the Foundry subnet NSG"
  value       = azurerm_network_security_group.foundry.id
}

output "private_dns_zone_cosmos_id" {
  description = "Resource ID of the Cosmos DB private DNS zone"
  value       = azurerm_private_dns_zone.cosmos.id
}

output "private_dns_zone_postgres_id" {
  description = "Resource ID of the PostgreSQL private DNS zone"
  value       = azurerm_private_dns_zone.postgres.id
}

output "private_dns_zone_acr_id" {
  description = "Resource ID of the ACR private DNS zone"
  value       = azurerm_private_dns_zone.acr.id
}

output "private_dns_zone_keyvault_id" {
  description = "Resource ID of the Key Vault private DNS zone"
  value       = azurerm_private_dns_zone.keyvault.id
}

output "private_dns_zone_cognitive_id" {
  description = "Resource ID of the Cognitive Services private DNS zone"
  value       = azurerm_private_dns_zone.cognitive.id
}

output "subnet_reserved_1_id" {
  description = "Resource ID of the reserved-1 subnet (Event Hub)"
  value       = azurerm_subnet.reserved_1.id
}

output "private_dns_zone_servicebus_id" {
  description = "Resource ID of the Service Bus private DNS zone"
  value       = azurerm_private_dns_zone.servicebus.id
}

output "subnet_acr_agent_pool_id" {
  description = "Resource ID of the ACR Tasks private agent pool subnet"
  value       = azurerm_subnet.acr_agent_pool.id
}
