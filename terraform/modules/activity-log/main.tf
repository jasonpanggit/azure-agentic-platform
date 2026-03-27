# Activity Log export to Log Analytics (AUDIT-003)
# Subscription-level diagnostic settings for all in-scope subscriptions.
#
# Exports all Activity Log categories to Log Analytics workspace for:
#   - Operational audit trail (Administrative, Policy)
#   - Security event capture (Security, Alert)
#   - Service health awareness (ServiceHealth, ResourceHealth)
#   - Platform change tracking (Recommendation, Autoscale)

resource "azurerm_monitor_diagnostic_setting" "activity_log" {
  for_each = toset(var.subscription_ids)

  name                       = "aap-activity-log-export-${var.environment}"
  target_resource_id         = "/subscriptions/${each.value}"
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "Administrative" }
  enabled_log { category = "Security" }
  enabled_log { category = "ServiceHealth" }
  enabled_log { category = "Alert" }
  enabled_log { category = "Recommendation" }
  enabled_log { category = "Policy" }
  enabled_log { category = "Autoscale" }
  enabled_log { category = "ResourceHealth" }
}
