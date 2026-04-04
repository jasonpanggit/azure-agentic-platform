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
  logs_destination               = "log-analytics"
  infrastructure_subnet_id       = var.container_apps_subnet_id
  infrastructure_resource_group_name = "ME_cae-aap-${var.environment}_${var.resource_group_name}_${replace(lower(var.location), " ", "")}"
  internal_load_balancer_enabled = false
  public_network_access          = "Enabled"

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
  public_network_access_enabled = false  # Private endpoint only; builds use private agent pool (VNet-injected)
  data_endpoint_enabled         = true

  # Allow Azure-internal services to bypass firewall (e.g. Terraform plan reads)
  network_rule_bypass_option = "AzureServices"

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

# NOTE: ACR private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).

# ── ACR Tasks Private Agent Pool ───────────────────────────────────────────────
# VNet-injected build agents so 'az acr build' can reach the private ACR endpoint.
# Runner calls: az acr build --registry <acr> --agent-pool aap-builder-<env> ...
resource "azurerm_container_registry_agent_pool" "main" {
  name                    = "aap-builder-${var.environment}"
  resource_group_name     = var.resource_group_name
  location                = var.location
  container_registry_name = azurerm_container_registry.main.name

  # S1: 2 vCPU, 3 GiB RAM — sufficient for sequential image builds
  instance_count          = 1
  tier                    = "S1"

  # Inject agents into our VNet so they reach ACR via private endpoint
  virtual_network_subnet_id = var.acr_agent_pool_subnet_id

  tags = var.required_tags

  depends_on = [azurerm_container_registry.main]
}
