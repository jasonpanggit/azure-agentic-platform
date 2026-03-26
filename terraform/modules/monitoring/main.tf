resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-aap-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = var.log_analytics_sku
  retention_in_days   = var.log_analytics_retention_days

  tags = var.required_tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-aap-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "other"

  tags = var.required_tags
}
