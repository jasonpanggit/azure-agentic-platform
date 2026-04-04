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
  default_outbound_access_enabled = false

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
  default_outbound_access_enabled   = false
  private_endpoint_network_policies = "Enabled"
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_postgres_cidr]
  default_outbound_access_enabled = false

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
  default_outbound_access_enabled   = false
  private_endpoint_network_policies = "Enabled"
}

resource "azurerm_subnet" "reserved_1" {
  name                 = "snet-reserved-1"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_reserved_1_cidr]
  default_outbound_access_enabled = false

  # Phase 4: Event Hub networking — service endpoint enables VNet rule on Event Hub namespace.
  service_endpoints = ["Microsoft.EventHub"]
}

# ACR Tasks private agent pool subnet — /27 minimum required by Azure, no delegation needed.
# Service endpoints required per: https://learn.microsoft.com/en-us/azure/container-registry/tasks-agent-pools
resource "azurerm_subnet" "acr_agent_pool" {
  name                 = "snet-acr-agent-pool"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_acr_agent_pool_cidr]
  default_outbound_access_enabled = false

  service_endpoints = [
    "Microsoft.AzureActiveDirectory",
    "Microsoft.EventHub",
    "Microsoft.KeyVault",
    "Microsoft.Storage",
  ]
}

# NSG for ACR Tasks agent pool subnet — required outbound rules per docs
resource "azurerm_network_security_group" "acr_agent_pool" {
  name                = "nsg-snet-acr-agent-pool-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.required_tags
}

resource "azurerm_network_security_rule" "acr_agent_pool_kv_out" {
  name                        = "AllowAzureKeyVaultOutbound"
  priority                    = 100
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureKeyVault"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.acr_agent_pool.name
}

resource "azurerm_network_security_rule" "acr_agent_pool_storage_out" {
  name                        = "AllowStorageOutbound"
  priority                    = 110
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Storage"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.acr_agent_pool.name
}

resource "azurerm_network_security_rule" "acr_agent_pool_eventhub_out" {
  name                        = "AllowEventHubOutbound"
  priority                    = 120
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "EventHub"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.acr_agent_pool.name
}

resource "azurerm_network_security_rule" "acr_agent_pool_aad_out" {
  name                        = "AllowAzureActiveDirectoryOutbound"
  priority                    = 130
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureActiveDirectory"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.acr_agent_pool.name
}

resource "azurerm_network_security_rule" "acr_agent_pool_monitor_out" {
  name                        = "AllowAzureMonitorOutbound"
  priority                    = 140
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_ranges     = ["443", "12000"]
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureMonitor"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.acr_agent_pool.name
}

# Allow MCR/Docker Hub pulls (build agents need to pull base images)
resource "azurerm_network_security_rule" "acr_agent_pool_internet_https_out" {
  name                        = "AllowInternetHTTPSOutbound"
  priority                    = 150
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "Internet"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.acr_agent_pool.name
}

resource "azurerm_subnet_network_security_group_association" "acr_agent_pool" {
  subnet_id                 = azurerm_subnet.acr_agent_pool.id
  network_security_group_id = azurerm_network_security_group.acr_agent_pool.id
}

# --- Network Security Groups ---

# Container Apps NSG — minimal rules; Container Apps manages its own networking
resource "azurerm_network_security_group" "container_apps" {
  name                = "nsg-snet-container-apps-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_network_security_rule" "container_apps_allow_vnet_inbound" {
  name                        = "AllowVNetInbound"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.container_apps.name
}

resource "azurerm_network_security_rule" "container_apps_allow_azure_outbound" {
  name                        = "AllowAzureCloudOutbound"
  priority                    = 100
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureCloud"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.container_apps.name
}

resource "azurerm_subnet_network_security_group_association" "container_apps" {
  subnet_id                 = azurerm_subnet.container_apps.id
  network_security_group_id = azurerm_network_security_group.container_apps.id
}

# Private Endpoints NSG — allow inbound from Container Apps subnet
resource "azurerm_network_security_group" "private_endpoints" {
  name                = "nsg-snet-private-endpoints-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_network_security_rule" "pe_allow_container_apps_inbound" {
  name                        = "AllowContainerAppsInbound"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_ranges     = ["443", "5432", "10255"]
  source_address_prefix       = var.subnet_container_apps_cidr
  destination_address_prefix  = var.subnet_private_endpoints_cidr
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.private_endpoints.name
}

resource "azurerm_network_security_rule" "pe_allow_acr_agent_pool_inbound" {
  name                        = "AllowAcrAgentPoolInbound"
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = var.subnet_acr_agent_pool_cidr
  destination_address_prefix  = var.subnet_private_endpoints_cidr
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.private_endpoints.name
}

resource "azurerm_network_security_rule" "pe_deny_all_inbound" {
  name                        = "DenyAllInbound"
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.private_endpoints.name
}

resource "azurerm_subnet_network_security_group_association" "private_endpoints" {
  subnet_id                 = azurerm_subnet.private_endpoints.id
  network_security_group_id = azurerm_network_security_group.private_endpoints.id
}

# PostgreSQL NSG — allow inbound TCP 5432 from Container Apps subnet only
resource "azurerm_network_security_group" "postgres" {
  name                = "nsg-snet-postgres-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_network_security_rule" "postgres_allow_container_apps" {
  name                        = "AllowPostgresFromContainerApps"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "5432"
  source_address_prefix       = var.subnet_container_apps_cidr
  destination_address_prefix  = var.subnet_postgres_cidr
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.postgres.name
}

resource "azurerm_network_security_rule" "postgres_deny_all_inbound" {
  name                        = "DenyAllInbound"
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.postgres.name
}

resource "azurerm_subnet_network_security_group_association" "postgres" {
  subnet_id                 = azurerm_subnet.postgres.id
  network_security_group_id = azurerm_network_security_group.postgres.id
}

# Foundry NSG (ISSUE-08) — allow inbound HTTPS from Container Apps subnet
resource "azurerm_network_security_group" "foundry" {
  name                = "nsg-snet-foundry-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_network_security_rule" "foundry_allow_container_apps_inbound" {
  name                        = "AllowContainerAppsInbound"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = var.subnet_container_apps_cidr
  destination_address_prefix  = var.subnet_foundry_cidr
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.foundry.name
}

resource "azurerm_network_security_rule" "foundry_deny_all_inbound" {
  name                        = "DenyAllInbound"
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.foundry.name
}

resource "azurerm_subnet_network_security_group_association" "foundry" {
  subnet_id                 = azurerm_subnet.foundry.id
  network_security_group_id = azurerm_network_security_group.foundry.id
}

# Reserved-1 NSG — Event Hub subnet; allow VNet traffic and Azure outbound HTTPS
resource "azurerm_network_security_group" "reserved_1" {
  name                = "nsg-snet-reserved-1-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_network_security_rule" "reserved_1_allow_vnet_inbound" {
  name                        = "AllowVNetInbound"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "VirtualNetwork"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.reserved_1.name
}

resource "azurerm_network_security_rule" "reserved_1_allow_azure_outbound" {
  name                        = "AllowAzureCloudOutbound"
  priority                    = 100
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureCloud"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.reserved_1.name
}

resource "azurerm_subnet_network_security_group_association" "reserved_1" {
  subnet_id                 = azurerm_subnet.reserved_1.id
  network_security_group_id = azurerm_network_security_group.reserved_1.id
}

# --- Private DNS Zones ---

resource "azurerm_private_dns_zone" "cosmos" {
  name                = "privatelink.documents.azure.com"
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_private_dns_zone" "acr" {
  name                = "privatelink.azurecr.io"
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_private_dns_zone" "keyvault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_private_dns_zone" "cognitive" {
  name                = "privatelink.cognitiveservices.azure.com"
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

# --- VNet Links ---

resource "azurerm_private_dns_zone_virtual_network_link" "cosmos" {
  name                  = "vnetlink-cosmos-${var.environment}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.cosmos.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = var.required_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "vnetlink-postgres-${var.environment}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = var.required_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  name                  = "vnetlink-acr-${var.environment}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.acr.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = var.required_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "keyvault" {
  name                  = "vnetlink-keyvault-${var.environment}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.keyvault.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = var.required_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "cognitive" {
  name                  = "vnetlink-cognitive-${var.environment}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.cognitive.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = var.required_tags
}

# --- Service Bus private DNS zone (for Event Hub private endpoint) ---

resource "azurerm_private_dns_zone" "servicebus" {
  name                = "privatelink.servicebus.windows.net"
  resource_group_name = var.resource_group_name

  tags = var.required_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "servicebus" {
  name                  = "vnetlink-servicebus-${var.environment}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.servicebus.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = var.required_tags
}
