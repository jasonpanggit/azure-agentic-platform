# --- NAT Gateway Public IP + Association imports ---
# pip-nat-acr-agent-pool-prod and its NAT gateway association already exist in Azure
# but are not in Terraform state. Import to avoid "resource already exists" error.
# Remove after first successful apply.

import {
  to = module.networking.azurerm_public_ip.acr_agent_pool_nat
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Network/publicIPAddresses/pip-nat-acr-agent-pool-prod"
}

import {
  to = module.networking.azurerm_nat_gateway_public_ip_association.acr_agent_pool
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Network/natGateways/nat-acr-agent-pool-prod|/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Network/publicIPAddresses/pip-nat-acr-agent-pool-prod"
}

# --- AI Services connection import (created manually during Phase 29 debugging) ---
# The aap-aiservices-connection was created manually on 2026-04-14 to link the Foundry
# model deployment to the capability host. Import to bring it under Terraform management.
# Remove after first successful apply.

import {
  to = module.foundry.azapi_resource.aiservices_connection
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod/connections/aap-aiservices-connection"
}

# --- Project-level capability host import (created manually during Phase 29 debugging) ---
# projectcaphost was created manually on 2026-04-14. Import to bring under Terraform management.
# Remove after first successful apply.

import {
  to = module.foundry.azapi_resource.project_capability_host
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod/projects/aap-project-prod/capabilityHosts/projectcaphost"
}

# --- Azure MCP Server Container App import (DEBT-013 / SEC-001) ---
# APPLIED 2026-04-02. Import blocks are one-shot — removed after successful apply.
# ca-azure-mcp-prod, its role assignments, and azure-mcp-connection are now in Terraform state.
# [ci-trigger: 2026-04-04 — re-enable state backend public access + 409 role assignment fix]

# --- Entra App Registration imports ---
# Imports the web-UI app registration (aap-web-ui-prod) created manually on 2026-03-28.
#
# BLOCKED until CI SP (65cf695c-1def-48ba-96af-d968218c90ba) has Application.ReadWrite.All
# admin-consented on the Entra tenant. See docs/BOOTSTRAP.md Step 1 for the one-time grant.
#
# Once the permission is granted:
#   1. Uncomment the two import blocks below
#   2. Run: terraform apply -var-file="credentials.tfvars"
#   3. Verify: terraform state list | grep azuread_application
#   4. Delete the import blocks (they are one-shot)
#
# aap-web-ui-prod details:
#   Object ID:          8176f860-9715-46e3-8875-5939a6b76a69
#   Service Principal:  c30c212c-7dc9-4c29-9147-3a22c64ab3c8 (SP object ID; appId = 505df1d3-3bd3-4151-ae87-6e5974b72a44)
#
# CLI alternative (once permission is granted):
#   terraform import -var-file="credentials.tfvars" \
#     'module.entra_apps[0].azuread_application.web_ui' \
#     '/applications/8176f860-9715-46e3-8875-5939a6b76a69'
#   terraform import -var-file="credentials.tfvars" \
#     'module.entra_apps[0].azuread_service_principal.web_ui' \
#     '505df1d3-3bd3-4151-ae87-6e5974b72a44'

# import {
#   to = module.entra_apps[0].azuread_application.web_ui
#   id = "/applications/8176f860-9715-46e3-8875-5939a6b76a69"
# }
#
# import {
#   to = module.entra_apps[0].azuread_service_principal.web_ui
#   id = "/servicePrincipals/c30c212c-7dc9-4c29-9147-3a22c64ab3c8"
# }

# --- RBAC role assignment import (409 Conflict fix) ---
# The api-gateway Reader role on subscription 4c727b88-... already exists in Azure
# (assignment ID: 344f496823dd404db298f1d4fad789de) but was not in Terraform state.
# Import block resolves the 409 RoleAssignmentExists error on terraform apply.
# Remove this block after the first successful apply.

import {
  to = module.rbac.azurerm_role_assignment.agent_rbac["api-gateway-reader-4c727b8812f44c919c2b372aab3bbae9"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/providers/Microsoft.Authorization/roleAssignments/344f496823dd404db298f1d4fad789de"
}

# --- API Gateway Monitoring Contributor + VM Contributor imports ---
# Manually assigned 2026-04-05 to enable AMA extension install and DCR management.
# Import blocks required to avoid 409 conflict on next terraform apply.
# Remove after first successful apply.

import {
  to = module.rbac.azurerm_role_assignment.agent_rbac["api-gateway-moncontrib-4c727b8812f44c919c2b372aab3bbae9"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/providers/Microsoft.Authorization/roleAssignments/7e7136d1-ba33-410d-b36e-70ab21871818"
}

import {
  to = module.rbac.azurerm_role_assignment.agent_rbac["api-gateway-vmcontrib-4c727b8812f44c919c2b372aab3bbae9"]
  id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/providers/Microsoft.Authorization/roleAssignments/ab6b0796-4ad6-4df2-b7db-caae36b4e0b2"
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

# --- Teams Bot Service imports (F-04) ---
# The Azure Bot resource (aap-teams-bot-prod) and its Entra app registration were created
# manually before module.teams_bot existed. Import blocks are required before enabling
# the module to avoid Terraform trying to create duplicate resources.
#
# PRE-REQUISITES before uncommenting:
#   1. Grant CI SP (65cf695c-1def-48ba-96af-d968218c90ba) Microsoft Graph
#      Application.ReadWrite.All (admin-consented) on the Entra tenant.
#   2. Set enable_teams_bot = true in terraform.tfvars.
#   3. Uncomment the four import blocks below.
#   4. Run: terraform apply -var-file="credentials.tfvars"
#   5. Verify: terraform state list | grep teams_bot
#   6. Delete these import blocks (they are one-shot).
#
# Resource details (sourced 2026-04-01):
#   Bot Service:          aap-teams-bot-prod  (F0 / SingleTenant)
#   Bot Service ID:       /subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.BotService/botServices/aap-teams-bot-prod
#   Entra App (client):   d5b074fc-7ca6-4354-8938-046e034d80da  (BOT_ID)
#   Entra App (object):   670e3ba4-eec6-4889-a7df-545953b5a1df
#   Service Principal:    4272985e-49e0-40dd-8b36-9e66c80b98f4
#
# NOTE: azuread_application_password cannot be imported — Entra does not expose secret
# values after creation. The existing BOT_PASSWORD secret is already set on the Container
# App via `az containerapp secret set` (see task F-04). After enabling this module, a NEW
# secret will be generated and stored in Key Vault; the operator must then run:
#   az containerapp secret set --name ca-teams-bot-prod --resource-group rg-aap-prod \
#     --secrets "teams-bot-password=$(az keyvault secret show --vault-name kv-aap-prod \
#     --name teams-bot-password-kv --query value -o tsv)"

# import {
#   to = module.teams_bot[0].azurerm_bot_service_azure_bot.main
#   id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.BotService/botServices/aap-teams-bot-prod"
# }

# import {
#   to = module.teams_bot[0].azuread_application.teams_bot
#   id = "/applications/670e3ba4-eec6-4889-a7df-545953b5a1df"
# }
#
# import {
#   to = module.teams_bot[0].azuread_service_principal.teams_bot
#   id = "/servicePrincipals/4272985e-49e0-40dd-8b36-9e66c80b98f4"
# }
#
# import {
#   to = module.teams_bot[0].azurerm_bot_channel_ms_teams.main
#   id = "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.BotService/botServices/aap-teams-bot-prod/channels/MsTeamsChannel"
# }
