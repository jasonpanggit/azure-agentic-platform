# Key Vault — RBAC authorization, no access policies
# Implementation: PLAN-03 (Wave 3)
#
# Settings:
#   - enable_rbac_authorization = true (no access policies)
#   - purge_protection_enabled = true
#   - soft_delete_retention_days = 90
#   - public_network_access_enabled = false
#
# Phase 1 scope: provision vault only. Secret seeding deferred to Phase 2.
#
# NOTE: Key Vault private endpoint is created by the dedicated
#       modules/private-endpoints module, NOT in this file.
