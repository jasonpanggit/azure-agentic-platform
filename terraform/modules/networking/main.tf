# Networking module — VNet, subnets, NSGs, private DNS zones
# Implementation: PLAN-02 (Wave 2)
#
# Resources created here:
#   - azurerm_virtual_network.main
#   - azurerm_subnet.container_apps (delegated: Microsoft.App/environments)
#   - azurerm_subnet.private_endpoints
#   - azurerm_subnet.postgres (delegated: Microsoft.DBforPostgreSQL/flexibleServers)
#   - azurerm_subnet.foundry (reserved for future PE)
#   - azurerm_subnet.reserved_1 (reserved for Phase 4 Event Hub)
#   - azurerm_network_security_group (per subnet, including foundry)
#   - azurerm_subnet_network_security_group_association (per subnet)
#   - azurerm_private_dns_zone (cosmos, postgres, acr, keyvault, cognitive)
#   - azurerm_private_dns_zone_virtual_network_link (per zone)
#
# NOTE: Private endpoints are NOT created in this module.
#       They live in the dedicated private-endpoints module (PLAN-03).

# --- Virtual Network ---

resource "azurerm_virtual_network" "main" {
  name                = "vnet-aap-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space       = var.vnet_address_space

  tags = var.required_tags
}

# --- Subnets ---

resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_container_apps_cidr]

  delegation {
    name = "container-apps-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = var.resource_group_name
  virtual_network_name              = azurerm_virtual_network.main.name
  address_prefixes                  = [var.subnet_private_endpoints_cidr]
  private_endpoint_network_policies = "Enabled"
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_postgres_cidr]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "foundry" {
  name                              = "snet-foundry"
  resource_group_name               = var.resource_group_name
  virtual_network_name              = azurerm_virtual_network.main.name
  address_prefixes                  = [var.subnet_foundry_cidr]
  private_endpoint_network_policies = "Enabled"
}

resource "azurerm_subnet" "reserved_1" {
  name                 = "snet-reserved-1"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_reserved_1_cidr]

  # Reserved for Phase 4 Event Hub networking. Do not use until Phase 4.
}
