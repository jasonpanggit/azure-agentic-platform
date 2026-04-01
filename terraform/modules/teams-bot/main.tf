# Teams Bot module — manages the Azure Bot service resource and its Entra app registration.
# The azurerm_container_app.teams_bot resource stays in agent-apps module.
# This module owns: Azure Bot resource, bot app registration, credentials in Key Vault.
#
# IMPORTANT: The Azure Bot resource (aap-teams-bot-prod) was created manually before
# this module existed. Import blocks live in terraform/envs/prod/imports.tf — uncomment
# them there and follow the pre-requisites before setting enable_teams_bot = true.
#
# Resource IDs (sourced 2026-04-01):
#   Bot Service:        /subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.BotService/botServices/aap-teams-bot-prod
#   Entra App (object): 670e3ba4-eec6-4889-a7df-545953b5a1df  (client: d5b074fc-7ca6-4354-8938-046e034d80da)
#   Service Principal:  4272985e-49e0-40dd-8b36-9e66c80b98f4
#
# Note: azuread_application_password cannot be imported — Entra does not expose secret values
# after creation. After enabling this module, a new secret will be created and stored in
# Key Vault. The operator must then sync it to the Container App secret:
#   az containerapp secret set --name ca-teams-bot-prod --resource-group rg-aap-prod \
#     --secrets "teams-bot-password=$(az keyvault secret show --vault-name kv-aap-prod \
#     --name teams-bot-password-kv --query value -o tsv)"

resource "azuread_application" "teams_bot" {
  display_name     = "aap-teams-bot-${var.environment}"
  sign_in_audience = "AzureADMyOrg"
}

resource "azuread_service_principal" "teams_bot" {
  client_id                    = azuread_application.teams_bot.client_id
  app_role_assignment_required = false
}

# IMPORTANT: Use a fixed end_date. timestamp() causes perpetual drift.
# Update this date during scheduled secret rotation.
resource "azuread_application_password" "teams_bot" {
  application_id = azuread_application.teams_bot.id
  display_name   = "teams-bot-secret-${var.environment}"
  end_date       = "2028-03-31T00:00:00Z"
}

resource "azurerm_bot_service_azure_bot" "main" {
  name                = "aap-teams-bot-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = "global"
  sku                 = var.bot_sku

  microsoft_app_id        = azuread_application.teams_bot.client_id
  microsoft_app_type      = "SingleTenant"
  microsoft_app_tenant_id = var.tenant_id

  # Messaging endpoint points to the teams-bot Container App
  endpoint = var.teams_bot_fqdn != "" ? "https://${var.teams_bot_fqdn}/api/messages" : ""

  tags = var.required_tags
}

# Teams channel — already enabled (msteams in configuredChannels).
# Import this resource when enabling the module:
#   import block in terraform/envs/prod/imports.tf (module.teams_bot[0].azurerm_bot_channel_ms_teams.main)
resource "azurerm_bot_channel_ms_teams" "main" {
  bot_name            = azurerm_bot_service_azure_bot.main.name
  location            = azurerm_bot_service_azure_bot.main.location
  resource_group_name = var.resource_group_name
}

# Store credentials in Key Vault — agent-apps module reads these
resource "azurerm_key_vault_secret" "bot_id" {
  name         = "teams-bot-id"
  value        = azuread_application.teams_bot.client_id
  key_vault_id = var.keyvault_id
}

resource "azurerm_key_vault_secret" "bot_password" {
  name         = "teams-bot-password-kv"
  value        = azuread_application_password.teams_bot.value
  key_vault_id = var.keyvault_id
}
