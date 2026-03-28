# Import existing Entra app registrations that were created outside Terraform.
# These import blocks tell Terraform to adopt existing resources on next apply
# rather than creating new ones.

# aap-web-ui-prod — created via az cli on 2026-03-28
# Object ID: 8176f860-9715-46e3-8875-5939a6b76a69 (az ad app show --id 505df1d3... --query id)
import {
  to = module.entra_apps.azuread_application.web_ui
  id = "/applications/8176f860-9715-46e3-8875-5939a6b76a69"
}

import {
  to = module.entra_apps.azuread_service_principal.web_ui
  id = "505df1d3-3bd3-4151-ae87-6e5974b72a44"
}
