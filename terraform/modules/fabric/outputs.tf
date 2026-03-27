output "fabric_capacity_id" {
  description = "Resource ID of the Fabric capacity"
  value       = azapi_resource.fabric_capacity.id
}

output "fabric_capacity_name" {
  description = "Name of the Fabric capacity"
  value       = "fc-aap-${var.environment}"
}

output "fabric_workspace_id" {
  description = "Resource ID of the Fabric workspace"
  value       = azapi_resource.fabric_workspace.id
}

output "fabric_eventhouse_id" {
  description = "Resource ID of the Fabric Eventhouse"
  value       = azapi_resource.fabric_eventhouse.id
}

output "fabric_kql_database_name" {
  description = "Name of the KQL database within the Eventhouse"
  value       = "kqldb-aap-${var.environment}"
}

output "fabric_activator_id" {
  description = "Resource ID of the Fabric Activator"
  value       = azapi_resource.fabric_activator.id
}

output "fabric_lakehouse_id" {
  description = "Resource ID of the OneLake Lakehouse"
  value       = azapi_resource.fabric_lakehouse.id
}
