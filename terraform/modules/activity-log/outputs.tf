output "diagnostic_setting_ids" {
  description = "Map of subscription ID to diagnostic setting resource ID"
  value       = { for k, v in azurerm_monitor_diagnostic_setting.activity_log : k => v.id }
}
