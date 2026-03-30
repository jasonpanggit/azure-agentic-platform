output "fabric_capacity_id" {
  description = "Resource ID of the Fabric capacity"
  value       = azapi_resource.fabric_capacity.id
}

output "fabric_capacity_name" {
  description = "Name of the Fabric capacity"
  value       = azapi_resource.fabric_capacity.name
}

output "fabric_workspace_id" {
  description = "Resource ID of the Fabric workspace"
  value       = try(azapi_resource.fabric_workspace[0].id, null)
}

output "fabric_eventhouse_id" {
  description = "Resource ID of the Fabric Eventhouse"
  value       = try(azapi_resource.fabric_eventhouse[0].id, null)
}

output "fabric_kql_database_name" {
  description = "Name of the KQL database within the Eventhouse"
  value       = var.enable_fabric_data_plane ? "kqldb-aap-${var.environment}" : null
}

output "fabric_activator_id" {
  description = "Resource ID of the Fabric Activator"
  value       = try(azapi_resource.fabric_activator[0].id, null)
}

output "fabric_lakehouse_id" {
  description = "Resource ID of the OneLake Lakehouse"
  value       = try(azapi_resource.fabric_lakehouse[0].id, null)
}
