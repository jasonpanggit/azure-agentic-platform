resource "azurerm_cognitive_account" "foundry" {
  name                          = "aap-foundry-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "aap-foundry-${var.environment}"
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

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = var.model_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "Standard"
    capacity = var.model_capacity
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
