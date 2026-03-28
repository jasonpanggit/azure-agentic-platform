# Entra ID app registrations for the Azure Agentic Platform
#
# Web UI app registration:
#   - Single-tenant (AzureADMyOrg)
#   - SPA redirect URIs for MSAL browser auth
#   - App roles for API scopes (incidents.read, approvals.write, chat.write)
#
# NOTE: NEXT_PUBLIC_* build args for the web-ui Docker image are sourced from
# GitHub Actions repo variables (set by the CI/CD workflow). This module
# manages the Entra app registration itself; the CI/CD pipeline reads the
# client_id output and passes it as a build arg when building the web-ui image.

# Web UI app registration
resource "azuread_application" "web_ui" {
  display_name     = "aap-web-ui-${var.environment}"
  sign_in_audience = "AzureADMyOrg"

  # SPA redirect URIs — MSAL browser (PublicClientApplication) uses SPA auth flow
  single_page_application {
    redirect_uris = compact(concat(
      var.web_ui_public_url != "" ? ["${var.web_ui_public_url}/callback"] : [],
      var.additional_redirect_uris,
    ))
  }

  # App roles for scoped access to API gateway
  app_role {
    allowed_member_types = ["User"]
    description          = "Read incidents and alerts"
    display_name         = "incidents.read"
    id                   = "a1b2c3d4-0001-0001-0001-000000000001"
    enabled              = true
    value                = "incidents.read"
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "Write remediation approvals"
    display_name         = "approvals.write"
    id                   = "a1b2c3d4-0002-0002-0002-000000000002"
    enabled              = true
    value                = "approvals.write"
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "Send chat messages to agents"
    display_name         = "chat.write"
    id                   = "a1b2c3d4-0003-0003-0003-000000000003"
    enabled              = true
    value                = "chat.write"
  }
}

resource "azuread_service_principal" "web_ui" {
  client_id = azuread_application.web_ui.client_id
  # Allow users in the tenant to consent individually
  app_role_assignment_required = false
}

# Store web-ui client ID in Key Vault for reference
resource "azurerm_key_vault_secret" "web_ui_client_id" {
  name         = "web-ui-client-id"
  value        = azuread_application.web_ui.client_id
  key_vault_id = var.keyvault_id
}
