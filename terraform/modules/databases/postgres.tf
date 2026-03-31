resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "aap-postgres-${var.environment}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = "16"
  sku_name                      = var.postgres_sku
  storage_mb                    = var.postgres_storage_mb
  delegated_subnet_id           = var.postgres_subnet_id
  private_dns_zone_id           = var.postgres_dns_zone_id
  public_network_access_enabled = false
  zone                          = "1"

  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = var.tenant_id
  }

  tags = var.required_tags
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "aap"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

# Allowlist pgvector extension (uppercase required by Azure)
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR"
}

# NOTE (ISSUE-04): The actual `CREATE EXTENSION IF NOT EXISTS vector;` SQL command
# is NOT run here via local-exec because the PostgreSQL server is VNet-injected with
# public_network_access_enabled = false. GitHub-hosted runners cannot reach it.
#
# Instead, pgvector extension creation is handled in the terraform-apply.yml workflow
# (PLAN-05, task 05.04) which:
#   1. Retrieves the runner's egress IP
#   2. Temporarily adds a firewall rule to the PostgreSQL server
#   3. Runs `CREATE EXTENSION IF NOT EXISTS vector;` via psql
#   4. Removes the firewall rule
#
# For manual bootstrap, run from a VNet-connected machine:
#   PGPASSWORD="..." psql -h <fqdn> -U aap_admin -d aap -c "CREATE EXTENSION IF NOT EXISTS vector;"

# PostgreSQL Entra auth administrator
# The server already has active_directory_auth_enabled = true.
# This assigns the API gateway managed identity as an Entra administrator,
# enabling token-based auth in addition to existing password auth.
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "api_gateway" {
  count = var.enable_postgres_entra_auth && var.api_gateway_principal_id != "" ? 1 : 0

  server_name         = azurerm_postgresql_flexible_server.main.name
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  object_id           = var.api_gateway_principal_id
  principal_name      = "ca-api-gateway-${var.environment}"
  principal_type      = "ServicePrincipal"
}
