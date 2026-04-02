locals {
  required_tags = {
    environment = var.environment
    managed-by  = "terraform"
    project     = "aap"
  }

  # Prod deploys the Arc MCP Server for Arc-specific tools (arc_servers_list, etc.)
  enable_arc_mcp_server = true
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
  model_capacity = 100
}

# --- Agent Managed Identity Principal IDs (for Cosmos data-plane RBAC) ---
# Cannot use module.agent_apps.agent_principal_ids here — that would create a circular
# dependency (agent_apps depends on databases). Data sources also fail because the
# container apps are managed resources in this same root (identity = known after apply).
#
# Instead, use a static map of principal IDs sourced from:
#   az containerapp show --name <app> --resource-group rg-aap-prod --query identity.principalId
# These GUIDs are stable for the lifetime of each Container App (tied to system-assigned MI).
# Update this map only if a Container App is destroyed and recreated.
locals {
  # System-assigned managed identity principal IDs for each agent Container App.
  # Sourced on 2026-03-31 via: az containerapp show --name ca-<agent>-prod \
  #   --resource-group rg-aap-prod --query identity.principalId -o tsv
  # These GUIDs are stable for the lifetime of each Container App (tied to system-assigned MI).
  # Update this map only if a Container App is destroyed and recreated.
  agent_cosmos_principal_ids = {
    "orchestrator" = "f4d7eea6-a1c9-4681-b2a2-08e32f9fe0da"
    "compute"      = "d8265243-d45a-4eda-a53f-56d201778536"
    "network"      = "c33a0182-a482-4842-8342-d1f7eab40e55"
    "storage"      = "9dd99cd2-45ba-47b4-aa27-3999bc85421c"
    "security"     = "f88d69e6-59b1-4d38-b0c8-4b5f890dc1dd"
    "arc"          = "7649f118-c7ee-42f1-8508-428e301ccb07"
    "sre"          = "cfb2fa91-678f-4b87-8250-617a8cc78ce8"
    "patch"        = "705c97ae-c77b-4f6f-ac28-05d432b09547"
    "eol"          = "76e4e593-861c-4c6c-b3f8-511269b4e893"
    "api-gateway"  = "69e05934-1feb-44d4-8fd2-30373f83ccec"
  }
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

  agent_principal_ids = local.agent_cosmos_principal_ids

  # PostgreSQL Entra auth: assign API gateway managed identity as Entra administrator
  # Principal ID sourced from: az containerapp show --name ca-api-gateway-prod \
  #   --resource-group rg-aap-prod --query identity.principalId -o tsv
  api_gateway_principal_id = "69e05934-1feb-44d4-8fd2-30373f83ccec"
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
  count  = local.enable_arc_mcp_server ? 1 : 0
  source = "../../modules/arc-mcp-server"

  resource_group_name            = azurerm_resource_group.main.name
  location                       = var.location
  environment                    = var.environment
  required_tags                  = local.required_tags
  container_apps_environment_id  = module.compute_env.container_apps_environment_id
  container_apps_env_domain      = module.compute_env.container_apps_environment_default_domain
  acr_login_server               = module.compute_env.acr_login_server
  acr_id                         = module.compute_env.acr_id
  app_insights_connection_string = module.monitoring.app_insights_connection_string

  # Prod: Arc resources may span multiple subscriptions.
  # Override arc_subscription_ids via all_subscription_ids or a dedicated variable.
  arc_subscription_ids = var.all_subscription_ids != [] ? var.all_subscription_ids : [var.subscription_id]

  arc_disconnect_alert_hours = 1

  # First apply: use placeholder image to break the chicken-and-egg cycle.
  # The Container App needs AcrPull role to pull from ACR, but the role can only
  # be assigned after the app (and its managed identity) exists. Placeholder image
  # lets the app provision; CI/CD deploys the real image once AcrPull is in place.
  # lifecycle { ignore_changes = [template[0].container[0].image] } prevents drift.
  use_placeholder_image = false
}

# --- Azure MCP Server (depends on: compute-env, monitoring) ---
# Phase 19 Plan 1: SEC-001 fix — internal-only ingress, no auth-bypass flag.
# The Container App was previously ad-hoc (DEBT-013); this module takes ownership.
# Import block in imports.tf handles the existing ca-azure-mcp-prod resource.

module "azure_mcp_server" {
  source = "../../modules/azure-mcp-server"

  environment                    = var.environment
  resource_group_name            = azurerm_resource_group.main.name
  location                       = var.location
  container_apps_environment_id  = module.compute_env.container_apps_environment_id
  acr_login_server               = module.compute_env.acr_login_server
  acr_id                         = module.compute_env.acr_id
  use_placeholder_image          = false
  image_tag                      = var.azure_mcp_image_tag
  subscription_id                = var.subscription_id
  app_insights_connection_string = module.monitoring.app_insights_connection_string
  required_tags                  = local.required_tags
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
  arc_mcp_server_url             = local.enable_arc_mcp_server ? module.arc_mcp_server[0].arc_mcp_server_url : ""
  azure_mcp_server_url           = "http://${module.azure_mcp_server.internal_fqdn}"
  compute_agent_id               = var.compute_agent_id
  network_agent_id               = var.network_agent_id
  storage_agent_id               = var.storage_agent_id
  security_agent_id              = var.security_agent_id
  sre_agent_id                   = var.sre_agent_id
  arc_agent_id                   = var.arc_agent_id
  patch_agent_id                 = var.patch_agent_id
  eol_agent_id                   = var.eol_agent_id

  # Use placeholder image on first deploy — ACR images don't exist yet.
  # CI/CD pipeline deploys real images after initial infra provisioning.
  # lifecycle.ignore_changes on image prevents Terraform from reverting CI/CD deploys.
  use_placeholder_image = true
  image_tag             = "latest"

  # Teams Bot specific configuration
  # When enable_teams_bot = true, bot credentials flow from module.teams_bot[0].
  # When enable_teams_bot = false (default), fall back to manual var.teams_bot_id / var.teams_bot_password.
  teams_bot_id             = var.enable_teams_bot ? module.teams_bot[0].bot_id : var.teams_bot_id
  teams_bot_password       = var.enable_teams_bot ? module.teams_bot[0].bot_password : var.teams_bot_password
  teams_bot_tenant_id      = var.teams_bot_tenant_id != "" ? var.teams_bot_tenant_id : var.tenant_id
  api_gateway_internal_url = "https://ca-api-gateway-${var.environment}.internal.${module.compute_env.container_apps_environment_default_domain}"
  web_ui_public_url        = var.web_ui_public_url
  teams_channel_id         = var.teams_channel_id

  # Web UI Observability tab
  log_analytics_workspace_customer_id = module.monitoring.log_analytics_workspace_customer_id

  # PostgreSQL DSN for agents that need direct DB access (e.g., eol-agent eol_cache table)
  postgres_dsn = var.postgres_dsn

  # PostgreSQL connection string for runbook RAG on the api-gateway (TRIAGE-005 / F-02)
  pgvector_connection_string = var.pgvector_connection_string
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

  # F-01 fix: grant Azure AI Developer to gateway MI on Foundry account
  resource_group_name  = azurerm_resource_group.main.name
  foundry_account_name = module.foundry.foundry_account_name
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

  resource_group_name      = azurerm_resource_group.main.name
  location                 = var.location
  environment              = var.environment
  required_tags            = local.required_tags
  fabric_capacity_sku      = "F4" # Prod: higher capacity
  fabric_admin_email       = var.fabric_admin_email
  fabric_capacity_name     = "fcaapprod"
  enable_fabric_data_plane = false
}

# --- Entra App Registrations (depends on: keyvault) ---
# Web UI app registration for MSAL browser auth (SPA flow).
# The client_id output is also stored in Key Vault and referenced by CI/CD
# as a GitHub Actions variable (NEXT_PUBLIC_AZURE_CLIENT_ID) for the web-ui image build.
#
# Gated behind var.enable_entra_apps because the azuread provider requires
# Microsoft Graph Application.ReadWrite.All permission on the Terraform SP.
# When disabled, manage app registrations manually via `az ad app` CLI.

module "entra_apps" {
  count  = var.enable_entra_apps ? 1 : 0
  source = "../../modules/entra-apps"

  environment       = var.environment
  web_ui_public_url = var.web_ui_public_url
  keyvault_id       = module.keyvault.keyvault_id
}

# --- Teams Bot (depends on: keyvault, agent-apps) ---
# Creates the Azure Bot service resource and bot app registration.
# The teams-bot Container App stays in module.agent_apps.
# Gate behind enable_teams_bot until bot registration credentials are ready
# and import blocks for the existing aap-teams-bot-prod resource are in place.
#
# Pre-requisites before enabling:
#   1. Grant Terraform SP: Microsoft Graph Application.ReadWrite.All
#   2. Uncomment import blocks in terraform/modules/teams-bot/main.tf
#   3. Set enable_teams_bot = true in terraform.tfvars

module "teams_bot" {
  count  = var.enable_teams_bot ? 1 : 0
  source = "../../modules/teams-bot"

  resource_group_name = azurerm_resource_group.main.name
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id
  keyvault_id         = module.keyvault.keyvault_id
  teams_bot_fqdn      = module.agent_apps.teams_bot_fqdn
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
# Only provisioned when both enable_entra_apps AND gateway_app_client_id are set.

resource "azuread_application" "fabric_sp" {
  count        = var.enable_entra_apps && var.gateway_app_client_id != "" ? 1 : 0
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
  count     = var.enable_entra_apps && var.gateway_app_client_id != "" ? 1 : 0
  client_id = azuread_application.fabric_sp[0].client_id
}

# IMPORTANT: Use a fixed end_date, NOT timeadd(timestamp(), ...).
# timestamp() returns a new value on every plan/apply, causing perpetual diff.
# See WARN-D4a in 04-01-PLAN.md. Update this date during scheduled secret rotation.
resource "azuread_application_password" "fabric_sp" {
  count          = var.enable_entra_apps && var.gateway_app_client_id != "" ? 1 : 0
  application_id = azuread_application.fabric_sp[0].id
  display_name   = "fabric-detection-secret"
  end_date       = "2027-03-26T00:00:00Z" # Fixed 1-year expiry — rotate before this date
}

resource "azurerm_key_vault_secret" "fabric_sp_client_id" {
  count        = var.enable_entra_apps && var.gateway_app_client_id != "" ? 1 : 0
  name         = "fabric-sp-client-id"
  value        = azuread_application.fabric_sp[0].client_id
  key_vault_id = module.keyvault.keyvault_id
}

resource "azurerm_key_vault_secret" "fabric_sp_client_secret" {
  count        = var.enable_entra_apps && var.gateway_app_client_id != "" ? 1 : 0
  name         = "fabric-sp-client-secret"
  value        = azuread_application_password.fabric_sp[0].value
  key_vault_id = module.keyvault.keyvault_id
}
