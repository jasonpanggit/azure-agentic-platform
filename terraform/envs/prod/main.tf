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

  # Prod: higher TPM capacity
  model_capacity = 30
}

# --- Databases (depends on: networking) ---

module "databases" {
  source = "../../modules/databases"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id

  # Cosmos DB — prod uses Provisioned Autoscale with multi-region HA
  cosmos_serverless         = false
  cosmos_secondary_location = "westus2"
  cosmos_max_throughput     = 4000

  # PostgreSQL — prod uses General Purpose SKU with 128 GB storage
  postgres_subnet_id      = module.networking.subnet_postgres_id
  postgres_dns_zone_id    = module.networking.private_dns_zone_postgres_id
  postgres_sku            = "GP_Standard_D4s_v3"
  postgres_storage_mb     = 131072
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

  # Phase 4: Event Hub private endpoint
  eventhub_namespace_id          = module.eventhub.eventhub_namespace_id
  private_dns_zone_servicebus_id = module.networking.private_dns_zone_servicebus_id
}

# --- Arc MCP Server (depends on: compute-env, monitoring) ---
# Phase 3: Internal-only Container App exposing Arc resource tools.
# Arc Agent calls it at http://{arc_mcp_server_fqdn}/mcp (ARC_MCP_SERVER_URL).

module "arc_mcp_server" {
  source = "../../modules/arc-mcp-server"

  resource_group_name            = azurerm_resource_group.main.name
  location                       = var.location
  environment                    = var.environment
  required_tags                  = local.required_tags
  container_apps_environment_id  = module.compute_env.container_apps_environment_id
  container_apps_env_domain      = module.compute_env.container_apps_environment_default_domain
  acr_login_server               = module.compute_env.acr_login_server
  app_insights_connection_string = module.monitoring.app_insights_connection_string

  # Prod: Arc resources may span multiple subscriptions.
  # Override arc_subscription_ids via all_subscription_ids or a dedicated variable.
  arc_subscription_ids = var.all_subscription_ids != [] ? var.all_subscription_ids : [var.subscription_id]

  arc_disconnect_alert_hours = 1
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
  foundry_project_endpoint       = module.foundry.foundry_project_endpoint
  foundry_project_id             = module.foundry.foundry_project_id
  foundry_model_deployment_name  = module.foundry.foundry_model_deployment_name
  app_insights_connection_string = module.monitoring.app_insights_connection_string
  cosmos_endpoint                = module.databases.cosmos_endpoint
  cosmos_database_name           = module.databases.cosmos_database_name
  cors_allowed_origins           = var.cors_allowed_origins
  orchestrator_agent_id          = var.orchestrator_agent_id
  arc_mcp_server_url             = module.arc_mcp_server.arc_mcp_server_url
  compute_agent_id               = var.compute_agent_id
  network_agent_id               = var.network_agent_id
  storage_agent_id               = var.storage_agent_id
  security_agent_id              = var.security_agent_id
  sre_agent_id                   = var.sre_agent_id
  arc_agent_id                   = var.arc_agent_id

  # Deploy real agent images from ACR (not placeholder)
  use_placeholder_image = false
  image_tag             = "latest"

  # Teams Bot specific configuration
  teams_bot_id             = var.teams_bot_id
  teams_bot_password       = var.teams_bot_password
  api_gateway_internal_url = "https://${module.compute_env.acr_login_server != "" ? "ca-api-gateway-${var.environment}.internal.${var.environment}.azurecontainerapps.io" : ""}"
  web_ui_public_url        = var.web_ui_public_url
  teams_channel_id         = var.teams_channel_id

  # Web UI Observability tab
  log_analytics_workspace_customer_id = module.monitoring.log_analytics_workspace_customer_id
}

# --- RBAC (depends on: agent-apps) ---

module "rbac" {
  source = "../../modules/rbac"

  agent_principal_ids      = module.agent_apps.agent_principal_ids
  platform_subscription_id = var.subscription_id
  all_subscription_ids     = var.all_subscription_ids
  acr_id                   = module.compute_env.acr_id

  # Prod: separate subscription IDs per domain for true isolation
  compute_subscription_id = var.compute_subscription_id
  network_subscription_id = var.network_subscription_id
  storage_subscription_id = var.storage_subscription_id
}

# --- Event Hub (depends on: networking) ---
# Phase 4: Azure Monitor alerts flow to Event Hub as the single ingest point.

module "eventhub" {
  source = "../../modules/eventhub"

  resource_group_name      = azurerm_resource_group.main.name
  location                 = var.location
  environment              = var.environment
  required_tags            = local.required_tags
  subnet_reserved_1_id     = module.networking.subnet_reserved_1_id
  eventhub_partition_count = 10 # Prod: 10 partitions for throughput
  eventhub_capacity        = 2
}

# --- Fabric (depends on: nothing, but logically after Event Hub) ---
# Phase 4: Fabric capacity, workspace, Eventhouse, Activator, OneLake lakehouse.

module "fabric" {
  source = "../../modules/fabric"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  fabric_capacity_sku = "F4" # Prod: higher capacity
  fabric_admin_email  = var.fabric_admin_email
}

# --- Entra App Registrations (depends on: keyvault) ---
# Web UI app registration for MSAL browser auth (SPA flow).
# The client_id output is also stored in Key Vault and referenced by CI/CD
# as a GitHub Actions variable (NEXT_PUBLIC_AZURE_CLIENT_ID) for the web-ui image build.

module "entra_apps" {
  source = "../../modules/entra-apps"

  environment      = var.environment
  web_ui_public_url = var.web_ui_public_url
  keyvault_id      = module.keyvault.keyvault_id
}

# --- Activity Log Export (depends on: monitoring) ---
# AUDIT-003: Export Activity Log from all subscriptions to Log Analytics.

module "activity_log" {
  source = "../../modules/activity-log"

  subscription_ids           = var.all_subscription_ids
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  environment                = var.environment
}

# --- Fabric Service Principal (D-08, D-09) ---
# App registration for the Fabric User Data Function to authenticate
# to the API gateway's POST /api/v1/incidents endpoint.
# Only provisioned when gateway_app_client_id is set.

resource "azuread_application" "fabric_sp" {
  count        = var.gateway_app_client_id != "" ? 1 : 0
  display_name = "aap-fabric-detection-${var.environment}"

  required_resource_access {
    resource_app_id = var.gateway_app_client_id

    resource_access {
      id   = var.gateway_incidents_write_role_id
      type = "Role"
    }
  }
}

resource "azuread_service_principal" "fabric_sp" {
  count     = var.gateway_app_client_id != "" ? 1 : 0
  client_id = azuread_application.fabric_sp[0].client_id
}

# IMPORTANT: Use a fixed end_date, NOT timeadd(timestamp(), ...).
# timestamp() returns a new value on every plan/apply, causing perpetual diff.
# See WARN-D4a in 04-01-PLAN.md. Update this date during scheduled secret rotation.
resource "azuread_application_password" "fabric_sp" {
  count          = var.gateway_app_client_id != "" ? 1 : 0
  application_id = azuread_application.fabric_sp[0].id
  display_name   = "fabric-detection-secret"
  end_date       = "2027-03-26T00:00:00Z" # Fixed 1-year expiry — rotate before this date
}

resource "azurerm_key_vault_secret" "fabric_sp_client_id" {
  count        = var.gateway_app_client_id != "" ? 1 : 0
  name         = "fabric-sp-client-id"
  value        = azuread_application.fabric_sp[0].client_id
  key_vault_id = module.keyvault.keyvault_id
}

resource "azurerm_key_vault_secret" "fabric_sp_client_secret" {
  count        = var.gateway_app_client_id != "" ? 1 : 0
  name         = "fabric-sp-client-secret"
  value        = azuread_application_password.fabric_sp[0].value
  key_vault_id = module.keyvault.keyvault_id
}
