output "role_assignment_count" {
  description = "Total number of RBAC role assignments created"
  value       = length(azurerm_role_assignment.agent_rbac)
}

output "role_assignments" {
  description = "Map of role assignment key to role details"
  value = {
    for key, ra in azurerm_role_assignment.agent_rbac :
    key => {
      principal_id         = ra.principal_id
      role_definition_name = ra.role_definition_name
      scope                = ra.scope
    }
  }
}
