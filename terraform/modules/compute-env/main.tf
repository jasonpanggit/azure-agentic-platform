# Container Apps Environment + Azure Container Registry
# Implementation: PLAN-03 (Wave 3)
#
# Container Apps Environment:
#   - Workload profiles mode (Consumption profile)
#   - internal_load_balancer_enabled = false (per-app ingress control)
#   - VNet integrated via container_apps_subnet_id
#
# ACR:
#   - Premium SKU (required for private endpoint)
#   - admin_enabled = false (managed identity auth)
#   - public_network_access_enabled = false
#   - Uses random_string suffix for globally unique name (ISSUE-10)
#
# NOTE: ACR private endpoint is created by the dedicated
#       modules/private-endpoints module, NOT in this file.
