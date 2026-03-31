# Import existing Entra app registrations that were created outside Terraform.
#
# These import blocks are DISABLED because the entra_apps module is gated behind
# var.enable_entra_apps (default: false). When enabling Entra app management,
# set enable_entra_apps = true in your tfvars and use CLI imports:
#
#   terraform import 'module.entra_apps[0].azuread_application.web_ui' '/applications/8176f860-9715-46e3-8875-5939a6b76a69'
#   terraform import 'module.entra_apps[0].azuread_service_principal.web_ui' '505df1d3-3bd3-4151-ae87-6e5974b72a44'
#
# Prerequisites:
#   - Terraform SP must have Microsoft Graph Application.ReadWrite.All permission
#   - Grant via: az ad app permission add --id <sp-client-id> --api 00000003-0000-0000-c000-000000000000 --api-permissions 1bfefb4e-e0b5-418b-a88f-73c46d2cc8e9=Role
#   - Then admin consent: az ad app permission admin-consent --id <sp-client-id>
#
# aap-web-ui-prod — created via az cli on 2026-03-28
# Object ID: 8176f860-9715-46e3-8875-5939a6b76a69 (az ad app show --id 505df1d3... --query id)

# --- Entra App Registration imports ---
# Imports the web-UI app registration created manually on 2026-03-28.
# Requires: var.enable_entra_apps = true AND CI SP has Application.ReadWrite.All (see docs/BOOTSTRAP.md)
#
# After successful import, `terraform plan` must show zero changes for these resources.

import {
  to = module.entra_apps[0].azuread_application.web_ui
  id = "/applications/8176f860-9715-46e3-8875-5939a6b76a69"
}

import {
  to = module.entra_apps[0].azuread_service_principal.web_ui
  id = "505df1d3-3bd3-4151-ae87-6e5974b72a44"
}

# --- Cosmos DB data-plane RBAC imports ---
# Assignment GUIDs from: az cosmosdb sql role assignment list --account-name aap-cosmos-prod --resource-group rg-aap-prod
# Run on: 2026-03-31
# Note: ca-patch-prod and ca-eol-prod had no existing assignments — Terraform will create them.
# Note: ca-web-ui-prod and ca-teams-bot-prod assignments exist in Azure but are NOT managed here
#       (they are out of scope for the databases module agent_principal_ids map).

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["orchestrator"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/4fad511b-c435-46bc-9031-fa11dc89eba2"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["compute"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/a648592a-edee-41dd-a179-66d8bad15c59"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["network"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/3d9fe423-0b59-475b-805b-b9045efdd071"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["storage"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/32638f3c-b960-4fb4-9ed7-95dce2721bff"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["security"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/5cbc1f46-9c34-42a2-942f-52bfaa6a063d"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["arc"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/ec8c04f1-8d98-40e0-b629-f1dd12c75320"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["sre"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/c74b819d-258d-45c0-9abe-ff989d419b2c"
}

import {
  to = module.databases.azurerm_cosmosdb_sql_role_assignment.data_contributor["api-gateway"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.DocumentDB/databaseAccounts/aap-cosmos-prod/sqlRoleAssignments/52969888-4f13-46c9-b48f-4f58ee95d193"
}
