# Cosmos DB — Serverless (dev/staging) or Provisioned Autoscale (prod)
# Implementation: PLAN-03 (Wave 3)
#
# Containers:
#   - incidents (partition key: /resource_id)
#   - approvals (partition key: /thread_id)
#
# NOTE: Private endpoint for Cosmos DB is created by the dedicated
#       modules/private-endpoints module, NOT in this file.
