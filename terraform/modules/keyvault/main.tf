resource "azurerm_key_vault" "main" {
  name                          = "kv-aap-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  public_network_access_enabled = false  # Runner is VNet-resident; public access not needed
  rbac_authorization_enabled    = true

  tags = var.required_tags
}

# NOTE: Key Vault private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).
