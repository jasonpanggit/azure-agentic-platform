# MCP Connections — Foundry Project Tool Surfaces (PROD-003)
#
# Each connection registers an MCP server on the Foundry project.
# All agents in the project can then invoke tools from that server.
# api-version 2026-01-01-preview is confirmed working (scripts/deploy-azure-mcp-server.sh:104)
#
# Dependency: Plan 19-1 must be applied first (Azure MCP Server internal ingress).
# The MCP connections point to internal FQDNs — public ingress is disabled after Plan 19-1.

locals {
  foundry_project_id = module.foundry.foundry_project_id
}

# Grant the CI/Terraform service principal "Azure AI Developer" on the Foundry account scope.
# The azapi_resource blocks below call the Foundry data-plane API
# (Microsoft.CognitiveServices/accounts/projects/connections) which requires this role —
# Contributor at subscription scope is insufficient for Foundry data-plane writes.
#
# This role assignment is narrow (Foundry account scope only) and is required only for
# terraform apply. It does NOT grant broad data access.
data "azuread_service_principal" "terraform_sp" {
  client_id = var.client_id
}

resource "azurerm_role_assignment" "terraform_sp_foundry_aidev" {
  principal_id         = data.azuread_service_principal.terraform_sp.object_id
  role_definition_name = "Azure AI Developer"
  scope                = module.foundry.foundry_account_id
}

# Azure MCP Server — primary tool surface (ARM, Monitor, Log Analytics, Advisor, Policy, Resource Health)
# Replaces the ad-hoc script registration from deploy-azure-mcp-server.sh:L104
# NOTE: category must be "CustomKeys" — "MCP" is not a valid enum for 2025-09-01 API.
# The existing connection (created manually) uses CustomKeys; we update target to internal FQDN.
resource "azapi_resource" "mcp_connection_azure" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-09-01"
  name      = "azure-mcp-connection"
  parent_id = local.foundry_project_id

  body = {
    properties = {
      category = "CustomKeys"
      target   = "http://${module.azure_mcp_server.internal_fqdn}"
      authType = "None" # Internal VNet — network boundary is sufficient; no token needed
      metadata = {
        description = "Azure MCP Server — ARM, Monitor, Log Analytics, Advisor, Policy, Resource Health"
        mcp_server  = "true"
        transport   = "http"
      }
    }
  }

  response_export_values  = ["*"]
  ignore_missing_property = true

  depends_on = [azurerm_role_assignment.terraform_sp_foundry_aidev]
}

# Arc MCP Server — custom Arc tool surface (AGENT-005)
# Covers Arc-enabled servers, Arc Kubernetes, and Arc data services
# (gap not covered by the Azure MCP Server)
# NOTE: category must be "CustomKeys" — "MCP" is not a valid enum for 2025-09-01 API.
resource "azapi_resource" "mcp_connection_arc" {
  count = local.enable_arc_mcp_server ? 1 : 0

  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-09-01"
  name      = "arc-mcp-connection"
  parent_id = local.foundry_project_id

  body = {
    properties = {
      category = "CustomKeys"
      target   = "http://${module.arc_mcp_server[0].internal_fqdn}"
      authType = "None" # Internal VNet — Arc MCP server uses Entra JWT validation
      metadata = {
        description = "Arc MCP Server — Arc Servers, Arc K8s, Arc Data Services"
        mcp_server  = "true"
        transport   = "http"
      }
    }
  }

  response_export_values  = ["*"]
  ignore_missing_property = true

  depends_on = [azurerm_role_assignment.terraform_sp_foundry_aidev]
}
