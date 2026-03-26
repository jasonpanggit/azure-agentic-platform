locals {
  required_tags = {
    environment = var.environment
    managed-by  = "terraform"
    project     = "aap"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-aap-${var.environment}"
  location = var.location

  tags = local.required_tags
}

# --- Monitoring (no dependencies) ---

module "monitoring" {
  source = "../../modules/monitoring"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
}

# --- Networking (no module dependencies) ---

module "networking" {
  source = "../../modules/networking"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags

  # NOTE (ISSUE-02): No resource IDs passed here. Private endpoints are
  # created by module.private_endpoints below, not by the networking module.
}

# --- Foundry (depends on: monitoring) ---

module "foundry" {
  source = "../../modules/foundry"

  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  environment                = var.environment
  required_tags              = local.required_tags
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
}

# --- Databases (depends on: networking) ---

module "databases" {
  source = "../../modules/databases"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id

  # Cosmos DB — staging uses Serverless
  cosmos_serverless = true

  # PostgreSQL — staging uses slightly larger burstable SKU
  postgres_subnet_id      = module.networking.subnet_postgres_id
  postgres_dns_zone_id    = module.networking.private_dns_zone_postgres_id
  postgres_sku            = "B_Standard_B2ms"
  postgres_storage_mb     = 65536
  postgres_admin_login    = "aap_admin"
  postgres_admin_password = var.postgres_admin_password

  # NOTE (ISSUE-01): No private_endpoint_subnet_id or private_dns_zone_cosmos_id
  # passed here. Cosmos DB PE is created by module.private_endpoints below.
}

# --- Compute Environment (depends on: networking, monitoring) ---

module "compute_env" {
  source = "../../modules/compute-env"

  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  environment                = var.environment
  required_tags              = local.required_tags
  container_apps_subnet_id   = module.networking.subnet_container_apps_id
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id

  # NOTE (ISSUE-01): No private_endpoint_subnet_id or private_dns_zone_acr_id
  # passed here. ACR PE is created by module.private_endpoints below.
}

# --- Key Vault (depends on: networking) ---

module "keyvault" {
  source = "../../modules/keyvault"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id

  # NOTE (ISSUE-01): No private_endpoint_subnet_id or private_dns_zone_keyvault_id
  # passed here. Key Vault PE is created by module.private_endpoints below.
}

# --- Private Endpoints (depends on: networking + ALL resource modules) ---
# ISSUE-01/ISSUE-02: Centralized PE module eliminates duplicates and circular deps.

module "private_endpoints" {
  source = "../../modules/private-endpoints"

  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  environment                = var.environment
  required_tags              = local.required_tags
  private_endpoint_subnet_id = module.networking.subnet_private_endpoints_id

  # Target resource IDs from upstream modules
  cosmos_account_id  = module.databases.cosmos_account_id
  acr_id             = module.compute_env.acr_id
  keyvault_id        = module.keyvault.keyvault_id
  foundry_account_id = module.foundry.foundry_account_id

  # DNS zone IDs from networking module
  private_dns_zone_cosmos_id    = module.networking.private_dns_zone_cosmos_id
  private_dns_zone_acr_id       = module.networking.private_dns_zone_acr_id
  private_dns_zone_keyvault_id  = module.networking.private_dns_zone_keyvault_id
  private_dns_zone_cognitive_id = module.networking.private_dns_zone_cognitive_id
}

# --- Agent Apps (depends on: compute-env, foundry, monitoring, databases) ---

module "agent_apps" {
  source = "../../modules/agent-apps"

  resource_group_name            = azurerm_resource_group.main.name
  location                       = var.location
  environment                    = var.environment
  required_tags                  = local.required_tags
  container_apps_environment_id  = module.compute_env.container_apps_environment_id
  acr_login_server               = module.compute_env.acr_login_server
  foundry_account_endpoint       = module.foundry.foundry_account_endpoint
  foundry_project_id             = module.foundry.foundry_project_id
  foundry_model_deployment_name  = module.foundry.foundry_model_deployment_name
  app_insights_connection_string = module.monitoring.app_insights_connection_string
  cosmos_endpoint                = module.databases.cosmos_endpoint
  cosmos_database_name           = module.databases.cosmos_database_name
}

# --- RBAC (depends on: agent-apps) ---

module "rbac" {
  source = "../../modules/rbac"

  agent_principal_ids      = module.agent_apps.agent_principal_ids
  platform_subscription_id = var.subscription_id
  all_subscription_ids     = [var.subscription_id]

  # In staging, all agents target the same subscription.
  # Override compute_subscription_id / network_subscription_id / storage_subscription_id
  # in prod via separate variables for true subscription isolation.
}
