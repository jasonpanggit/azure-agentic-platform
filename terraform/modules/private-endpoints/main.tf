# Private Endpoints module — centralized PE creation for all platform services
# Implementation: PLAN-03, task 03.07 (Wave 3)
#
# This module depends on BOTH the networking module (for subnet + DNS zone IDs)
# AND the resource modules (for target resource IDs). It must be instantiated
# AFTER all resource modules in the environment root.
#
# Resources created here:
#   - azurerm_private_endpoint.cosmos (subresource: "Sql")
#   - azurerm_private_endpoint.acr (subresource: "registry")
#   - azurerm_private_endpoint.keyvault (subresource: "vault")
#   - azurerm_private_endpoint.foundry (subresource: "account")
#
# NOTE: PostgreSQL Flexible Server uses VNet injection (delegated subnet),
#       NOT a private endpoint. No PE is created for PostgreSQL.
