# Private Endpoints module — centralized PE creation for all platform services.
#
# This module depends on:
#   - networking module (for subnet_id and DNS zone IDs)
#   - databases module (for cosmos_account_id)
#   - compute-env module (for acr_id)
#   - keyvault module (for keyvault_id)
#   - foundry module (for foundry_account_id)
#
# It must be instantiated AFTER all resource modules in the environment root.
#
# PostgreSQL Flexible Server uses VNet injection (delegated subnet),
# NOT a private endpoint. No PE is created for PostgreSQL.

resource "azurerm_private_endpoint" "cosmos" {
  name                = "pe-cosmos-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-cosmos-${var.environment}"
    private_connection_resource_id = var.cosmos_account_id
    is_manual_connection           = false
    subresource_names              = ["Sql"]
  }

  private_dns_zone_group {
    name                 = "dns-cosmos"
    private_dns_zone_ids = [var.private_dns_zone_cosmos_id]
  }

  tags = var.required_tags
}

resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-acr-${var.environment}"
    private_connection_resource_id = var.acr_id
    is_manual_connection           = false
    subresource_names              = ["registry"]
  }

  private_dns_zone_group {
    name                 = "dns-acr"
    private_dns_zone_ids = [var.private_dns_zone_acr_id]
  }

  tags = var.required_tags
}

resource "azurerm_private_endpoint" "keyvault" {
  name                = "pe-keyvault-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-keyvault-${var.environment}"
    private_connection_resource_id = var.keyvault_id
    is_manual_connection           = false
    subresource_names              = ["vault"]
  }

  private_dns_zone_group {
    name                 = "dns-keyvault"
    private_dns_zone_ids = [var.private_dns_zone_keyvault_id]
  }

  tags = var.required_tags
}

resource "azurerm_private_endpoint" "foundry" {
  name                = "pe-foundry-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-foundry-${var.environment}"
    private_connection_resource_id = var.foundry_account_id
    is_manual_connection           = false
    subresource_names              = ["account"]
  }

  private_dns_zone_group {
    name                 = "dns-cognitive"
    private_dns_zone_ids = [var.private_dns_zone_cognitive_id]
  }

  tags = var.required_tags
}
