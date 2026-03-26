# Capability Host — required for Foundry Hosted Agents (Phase 2)
# Uses azapi because this resource type is not available in azurerm.
#
# KNOWN ISSUES:
# - Long-running operation (up to 30 min) — extended timeouts configured
# - May show perpetual drift on specific properties — lifecycle ignore_changes used
# - enablePublicHostingEnvironment = true is REQUIRED during Preview (no private networking)

resource "azapi_resource" "capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview"
  name      = "accountcaphost"
  parent_id = azurerm_cognitive_account.foundry.id

  body = {
    properties = {
      capabilityHostKind             = "Agents"
      enablePublicHostingEnvironment = true
    }
  }

  timeouts {
    create = "30m"
    delete = "30m"
  }

  lifecycle {
    ignore_changes = [
      body.properties.enablePublicHostingEnvironment,
    ]
  }
}
