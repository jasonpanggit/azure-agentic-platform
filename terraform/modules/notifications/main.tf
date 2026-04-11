# Azure Communication Services — Email (Phase 30: SOP Engine)
#
# Provisions ACS Email for the sop_notify @ai_function to send email
# notifications when SOP steps require it. Connection string is stored
# in Key Vault and injected into agent Container Apps as ACS_CONNECTION_STRING.

resource "azurerm_email_communication_service" "acs_email" {
  name                = "aap-acs-email-${var.environment}"
  resource_group_name = var.resource_group_name
  data_location       = var.data_location
}

resource "azurerm_communication_service" "acs" {
  name                = "aap-acs-${var.environment}"
  resource_group_name = var.resource_group_name
  data_location       = var.data_location

  tags = var.required_tags
}
