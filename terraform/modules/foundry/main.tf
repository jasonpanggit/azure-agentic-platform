resource "azurerm_cognitive_account" "foundry" {
  name                          = "aap-foundry-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "aap-foundry-${var.environment}"
  local_auth_enabled            = false
  public_network_access_enabled = true # Required during Preview for Hosted Agents
  project_management_enabled    = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

resource "azurerm_cognitive_account_project" "main" {
  name                 = "aap-project-${var.environment}"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

# gpt-4.1 deployment — required by all agent definitions (orchestrator, domain agents)
# Deployed manually 2026-04-17; managed here to prevent drift.
resource "azurerm_cognitive_deployment" "gpt41" {
  name                 = "gpt-4.1"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = "gpt-4.1"
    version = "2025-04-14"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 100
  }

  lifecycle {
    # Prevent re-provisioning on capacity drift — capacity is set via Azure Portal quota
    ignore_changes = [sku]
  }
}

# Diagnostic settings for Foundry account
resource "azurerm_monitor_diagnostic_setting" "foundry" {
  name                       = "diag-foundry-${var.environment}"
  target_resource_id         = azurerm_cognitive_account.foundry.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}
