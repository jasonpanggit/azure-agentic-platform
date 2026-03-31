# Arc MCP Server — Internal Container App (AGENT-005)
#
# Deployed as internal-only (external_enabled = false). The Arc MCP Server
# has an explicit ingress block with external_enabled=false so agents can
# reach it via internal DNS: http://ca-arc-mcp-server-{env}.{domain}/mcp
#
# This is different from the agent-apps pattern which omits the ingress block
# entirely for internal apps (giving no internal FQDN). The Arc MCP Server
# NEEDS an internal FQDN for agent-to-server communication.

resource "azurerm_container_app" "arc_mcp_server" {
  name                         = "ca-arc-mcp-server-${var.environment}"
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
  registry {
    server   = var.acr_login_server
    identity = "system"
  }

  # INTERNAL INGRESS — not publicly accessible, reachable within Container Apps env
  ingress {
    external_enabled = false # Internal only — AGENT-005 success criteria SC-1
    target_port      = 8080  # FastMCP streamable-http port
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
      name   = "arc-mcp-server"
      image  = "${var.acr_login_server}/services/arc-mcp-server:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      # Disconnection alert threshold (MONITOR-004)
      env {
        name  = "ARC_DISCONNECT_ALERT_HOURS"
        value = tostring(var.arc_disconnect_alert_hours)
      }

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

  # Runtime image revisions are owned by CI/CD — ignore drift from manual deploys.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
    ]
  }
}

# ---------------------------------------------------------------------------
# RBAC: Reader on each Arc subscription for the Arc MCP Server identity
# ---------------------------------------------------------------------------
# Reader covers:
#   - Microsoft.HybridCompute/machines/read (Arc Servers)
#   - Microsoft.Kubernetes/connectedClusters/read (Arc K8s)
#   - Microsoft.KubernetesConfiguration/fluxConfigurations/read (Flux — MONITOR-006)
#   - Microsoft.HybridData/read (Arc Data Services)

resource "azurerm_role_assignment" "arc_mcp_reader" {
  for_each = toset(var.arc_subscription_ids)

  principal_id         = azurerm_container_app.arc_mcp_server.identity[0].principal_id
  role_definition_name = "Reader"
  scope                = "/subscriptions/${each.value}"

  depends_on = [azurerm_container_app.arc_mcp_server]
}

# ---------------------------------------------------------------------------
# RBAC: AcrPull on ACR for image pull via system-assigned managed identity
# ---------------------------------------------------------------------------
# The registry block above uses identity = "system", which requires the
# Container App's managed identity to have AcrPull on the ACR.

resource "azurerm_role_assignment" "arc_mcp_acr_pull" {
  count = var.acr_id != "" ? 1 : 0

  principal_id         = azurerm_container_app.arc_mcp_server.identity[0].principal_id
  role_definition_name = "AcrPull"
  scope                = var.acr_id

  depends_on = [azurerm_container_app.arc_mcp_server]
}
