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
