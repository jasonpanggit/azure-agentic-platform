output "cosmos_private_endpoint_id" {
  description = "Resource ID of the Cosmos DB private endpoint"
  value       = azurerm_private_endpoint.cosmos.id
}

output "acr_private_endpoint_id" {
  description = "Resource ID of the ACR private endpoint"
  value       = azurerm_private_endpoint.acr.id
}

output "keyvault_private_endpoint_id" {
  description = "Resource ID of the Key Vault private endpoint"
  value       = azurerm_private_endpoint.keyvault.id
}

output "foundry_private_endpoint_id" {
  description = "Resource ID of the Foundry private endpoint"
  value       = azurerm_private_endpoint.foundry.id
}
