output "eventhub_namespace_id" {
  description = "Resource ID of the Event Hub namespace"
  value       = azurerm_eventhub_namespace.main.id
}

output "eventhub_namespace_name" {
  description = "Name of the Event Hub namespace"
  value       = azurerm_eventhub_namespace.main.name
}

output "eventhub_name" {
  description = "Name of the raw-alerts Event Hub"
  value       = "raw-alerts"
}

output "eventhub_send_rule_primary_connection_string" {
  description = "Primary connection string for the action-group-send authorization rule"
  value       = azurerm_eventhub_namespace_authorization_rule.action_group_send.primary_connection_string
  sensitive   = true
}

output "eventhub_listen_rule_primary_connection_string" {
  description = "Primary connection string for the eventhouse-listen authorization rule"
  value       = azurerm_eventhub_namespace_authorization_rule.eventhouse_listen.primary_connection_string
  sensitive   = true
}

output "action_group_id" {
  description = "Resource ID of the Azure Monitor Action Group"
  value       = azurerm_monitor_action_group.main.id
}
