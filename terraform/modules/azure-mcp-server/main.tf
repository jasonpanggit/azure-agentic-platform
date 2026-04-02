# Azure MCP Server — Internal Container App (SEC-001 / DEBT-013)
#
# Deployed as internal-only (external_enabled = false). The Azure MCP Server
# has an explicit ingress block with external_enabled=false so agents can
# reach it via internal DNS: http://ca-azure-mcp-{env}.{domain}/mcp
#
# This resolves SEC-001 (CRITICAL): previously the Container App was
# internet-accessible with --dangerously-disable-http-incoming-auth, allowing
# any unauthenticated internet user to enumerate all Azure resource metadata.
#
# Defense-in-depth: network boundary (internal ingress) + process boundary
# (no --dangerously-disable-http-incoming-auth flag in Dockerfile).
#
# Pattern mirrors terraform/modules/arc-mcp-server/main.tf.

resource "azurerm_container_app" "azure_mcp_server" {
  name                         = "ca-azure-mcp-${var.environment}"
  container_app_environment_id = var.container_apps_environment_id
  resource_group_name          = var.resource_group_name
  max_inactive_revisions       = 0
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type = "SystemAssigned"
  }

  # ACR registry configuration — uses managed identity for image pull (no admin credentials)
  # Matches the agent-apps pattern: system-assigned MI authenticates to ACR.
  # When use_placeholder_image is true, skip the registry block to avoid the chicken-and-egg
  # problem: the MI needs AcrPull but that role is assigned AFTER the app is created.
  dynamic "registry" {
    for_each = var.use_placeholder_image ? [] : [1]
    content {
      server   = var.acr_login_server
      identity = "system"
    }
  }

  # INTERNAL INGRESS — not publicly accessible, reachable within Container Apps env
  # SEC-001: external_enabled = false is the primary security control.
  ingress {
    external_enabled = false # Internal only — SEC-001 fix
    target_port      = 8080
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "azure-mcp-server"
      image  = var.use_placeholder_image ? "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" : "${var.acr_login_server}/services/azure-mcp-server:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      # Application Insights (MONITOR-007 OpenTelemetry)
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }
    }
  }

  secret {
    name  = "appinsights-connection-string"
    value = var.app_insights_connection_string
  }

  tags = var.required_tags

  # Runtime image and port revisions are owned by CI/CD — ignore drift from manual deploys.
  # ingress[0].target_port is also ignored so CI/CD can update port without Terraform reverting.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      ingress[0].target_port,
    ]
  }
}

# ---------------------------------------------------------------------------
# RBAC: Reader on subscription for the Azure MCP Server managed identity
# ---------------------------------------------------------------------------
# Reader covers all Azure ARM resource types exposed via Azure MCP Server:
#   - Microsoft.Compute/* (VMs, VMSS, disks)
#   - Microsoft.Network/* (VNets, NSGs)
#   - Microsoft.Storage/* (storage accounts)
#   - Microsoft.Monitor/* (Log Analytics, metrics)
#   - and 40+ other ARM resource types

resource "azurerm_role_assignment" "azure_mcp_reader" {
  principal_id         = azurerm_container_app.azure_mcp_server.identity[0].principal_id
  role_definition_name = "Reader"
  scope                = "/subscriptions/${var.subscription_id}"

  depends_on = [azurerm_container_app.azure_mcp_server]
}

# ---------------------------------------------------------------------------
# RBAC: AcrPull on ACR for image pull via system-assigned managed identity
# ---------------------------------------------------------------------------
# The registry block above uses identity = "system", which requires the
# Container App's managed identity to have AcrPull on the ACR.

resource "azurerm_role_assignment" "azure_mcp_acr_pull" {
  count = var.acr_id != "" ? 1 : 0

  principal_id         = azurerm_container_app.azure_mcp_server.identity[0].principal_id
  role_definition_name = "AcrPull"
  scope                = var.acr_id

  depends_on = [azurerm_container_app.azure_mcp_server]
}
