# Teams Bot module — manages the Azure Bot service resource and its Entra app registration.
# The azurerm_container_app.teams_bot resource stays in agent-apps module.
# This module owns: Azure Bot resource, bot app registration, credentials in Key Vault.
#
# IMPORTANT: The Azure Bot resource (aap-teams-bot-prod) was created manually before
# this module existed. When enabling this module for the first time, import the existing
# resources using the import blocks below (uncomment and run `terraform apply`):
#
# import {
#   to = azurerm_bot_service_azure_bot.main
#   id = "/subscriptions/<subscription_id>/resourceGroups/rg-aap-prod/providers/Microsoft.BotService/botServices/aap-teams-bot-prod"
# }
#
# The Entra app registration (msaAppId: d5b074fc-7ca6-4354-8938-046e034d80da) was also
# created out-of-band. Import it before applying to avoid creating a duplicate:
#
# import {
#   to = azuread_application.teams_bot
#   id = "<object_id_of_app_registration>"  # az ad app show --id d5b074fc-7ca6-4354-8938-046e034d80da --query id -o tsv
# }
#
# import {
#   to = azuread_service_principal.teams_bot
#   id = "<object_id_of_service_principal>"  # az ad sp show --id d5b074fc-7ca6-4354-8938-046e034d80da --query id -o tsv
# }
#
# Note: azuread_application_password cannot be imported — Entra does not expose secret values
# after creation. After enabling this module, a new secret will be created and stored in
# Key Vault. Update the Container App env var BOT_PASSWORD to use the new KV reference.

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
