# Cosmos DB outputs
output "cosmos_account_id" {
  description = "Resource ID of the Cosmos DB account"
  value       = azurerm_cosmosdb_account.main.id
}

output "cosmos_account_name" {
  description = "Name of the Cosmos DB account"
  value       = azurerm_cosmosdb_account.main.name
}

output "cosmos_endpoint" {
  description = "Endpoint URL of the Cosmos DB account"
  value       = azurerm_cosmosdb_account.main.endpoint
}

output "cosmos_database_name" {
  description = "Name of the Cosmos DB SQL database"
  value       = azurerm_cosmosdb_sql_database.main.name
}

# PostgreSQL outputs
output "postgres_server_id" {
  description = "Resource ID of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.main.id
}

output "postgres_fqdn" {
  description = "FQDN of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_database_name" {
  description = "Name of the PostgreSQL database"
  value       = azurerm_postgresql_flexible_server_database.main.name
}

output "cosmos_sessions_container_name" {
  description = "Name of the Cosmos DB sessions container for budget tracking (AGENT-007)"
  value       = azurerm_cosmosdb_sql_container.sessions.name
}

output "cosmos_topology_container_name" {
  description = "Name of the Cosmos DB topology container for the resource property graph (TOPO-001)"
  value       = azurerm_cosmosdb_sql_container.topology.name
}

output "cosmos_baselines_container_name" {
  description = "Name of the Cosmos DB baselines container for capacity forecasting (INTEL-005)"
  value       = azurerm_cosmosdb_sql_container.baselines.name
}

output "cosmos_remediation_audit_container_name" {
  description = "Name of the Cosmos DB remediation_audit container for WAL and immutable audit trail (REMEDI-011, REMEDI-013)"
  value       = azurerm_cosmosdb_sql_container.remediation_audit.name
}

output "cosmos_pattern_analysis_container_name" {
  description = "Name of the Cosmos DB pattern_analysis container for platform intelligence (PLATINT-001)"
  value       = azurerm_cosmosdb_sql_container.pattern_analysis.name
}

output "cosmos_business_tiers_container_name" {
  description = "Name of the Cosmos DB business_tiers container for FinOps tier configuration (PLATINT-004)"
  value       = azurerm_cosmosdb_sql_container.business_tiers.name
}

output "cosmos_policy_suggestions_container_name" {
  description = "Name of the Cosmos DB policy_suggestions container for learning suggestion engine (Phase 51)"
  value       = azurerm_cosmosdb_sql_container.policy_suggestions.name
}
