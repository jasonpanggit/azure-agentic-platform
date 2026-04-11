output "acs_name" {
  description = "Name of the Azure Communication Service"
  value       = azurerm_communication_service.acs.name
}

output "acs_email_name" {
  description = "Name of the ACS Email Communication Service"
  value       = azurerm_email_communication_service.acs_email.name
}
