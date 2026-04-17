# fabric/kql

KQL definitions for the Eventhouse that powers the detection plane. Covers table schemas, data retention, ingestion policies, and the Activator trigger queries that classify and route Azure Monitor alerts into platform incidents.

## Contents

- `schemas/` — `.kql` table schema definitions (alert ingestion tables, resource inventory)
- `retention/` — data retention and hot-cache policies per table
- `policies/` — ingestion mappings and update policies
- `functions/` — KQL stored functions including `classify_domain()` for routing alerts to domain agents
