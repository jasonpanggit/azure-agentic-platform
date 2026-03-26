# Random suffix for globally unique ACR name (ISSUE-10)
resource "random_string" "acr_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_container_app_environment" "main" {
  name                           = "cae-aap-${var.environment}"
  location                       = var.location
  resource_group_name            = var.resource_group_name
  log_analytics_workspace_id     = var.log_analytics_workspace_id
  infrastructure_subnet_id       = var.container_apps_subnet_id
  internal_load_balancer_enabled = false

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }

  tags = var.required_tags
}

resource "azurerm_container_registry" "main" {
  name                          = "aapcr${var.environment}${random_string.acr_suffix.result}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = false
  data_endpoint_enabled         = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

# NOTE: ACR private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).
