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
