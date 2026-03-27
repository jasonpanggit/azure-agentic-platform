# AUDIT-003: Activity Log OneLake Mirror Setup

## Overview

AUDIT-003 requires Activity Log data "mirrored to Fabric OneLake; retention is >= 2 years in OneLake."

Activity Log data flows through this pipeline:
1. **Azure Monitor Activity Log** -> **Log Analytics workspace** (automated via Terraform diagnostic settings in Task 4-01-06)
2. **Log Analytics workspace** -> **Fabric OneLake Lakehouse** (manual setup documented below)
3. **OneLake Lakehouse retention** set to >= 730 days (2 years)

Steps 2 and 3 cannot be fully automated via Terraform or the Fabric REST API as of 2026-03-26. This document provides the manual configuration steps.

## Prerequisites

- Fabric workspace `aap-{environment}` exists (provisioned by Task 4-01-01)
- OneLake Lakehouse `lh-aap-{environment}` exists within the workspace (provisioned by Task 4-01-01)
- Log Analytics workspace is receiving Activity Log data (provisioned by Task 4-01-06)
- Fabric capacity is active and has sufficient CU quota

## Step 1: Create OneLake Shortcut to Log Analytics

**Option A: OneLake Shortcut (Preferred)**

1. Open the Fabric portal: https://app.fabric.microsoft.com
2. Navigate to workspace `aap-{environment}`
3. Open lakehouse `lh-aap-{environment}`
4. Click **Get data** -> **New shortcut**
5. Select **Azure Data Lake Storage Gen2** as the source
6. Configure the shortcut:
   - **URL**: The Log Analytics workspace export storage account URL
   - **Path**: `/AzureActivityLog/` (the diagnostic export path)
   - **Shortcut name**: `ActivityLog`
7. Click **Create**

**Option B: Fabric Data Pipeline (Alternative)**

If OneLake shortcuts do not support direct Log Analytics access:

1. Open the Fabric portal
2. Navigate to workspace `aap-{environment}`
3. Click **New** -> **Data Pipeline**
4. Name: `pipeline-activity-log-mirror`
5. Add a **Copy Data** activity:
   - **Source**: Azure Log Analytics workspace
     - Connection: Use managed identity or service principal
     - Query: `AzureActivity | where TimeGenerated > ago(1h)`
   - **Destination**: OneLake Lakehouse `lh-aap-{environment}`
     - Table: `ActivityLog`
     - Format: Delta/Parquet
6. Set schedule: **Every 1 hour**
7. Enable the pipeline

## Step 2: Configure retention (>= 2 years / 730 days)

Fabric OneLake retention is configured at the lakehouse table level:

1. Open lakehouse `lh-aap-{environment}` in Fabric portal
2. Navigate to the `ActivityLog` table
3. Open **Table properties** -> **Retention policy**
4. Set retention period to **730 days** (2 years minimum, per AUDIT-003)
5. Set retention action to **Delete** (expired data is permanently removed)
6. Click **Save**

**Alternative: Delta Lake table properties**

If Fabric portal does not expose retention settings directly, configure via Spark notebook:

```python
# Run in a Fabric Spark notebook attached to the lakehouse
spark.sql("""
ALTER TABLE ActivityLog
SET TBLPROPERTIES (
  'delta.deletedFileRetentionDuration' = 'interval 730 days',
  'delta.logRetentionDuration' = 'interval 730 days'
)
""")
```

## Step 3: Verify Configuration

1. **Verify data flow**: Run KQL query against OneLake:
   ```kql
   ActivityLog
   | where TimeGenerated > ago(5m)
   | take 10
   ```
   Expected: Recent activity log events appear within 5 minutes of source event.

2. **Verify retention**: Check table properties confirm 730-day retention:
   ```python
   spark.sql("DESCRIBE DETAIL ActivityLog").select("properties").show(truncate=False)
   ```
   Expected: `delta.deletedFileRetentionDuration` = `interval 730 days`

3. **Verify historical data**: Confirm data older than 1 day exists:
   ```kql
   ActivityLog
   | where TimeGenerated < ago(1d)
   | count
   ```
   Expected: Count > 0 (after pipeline has been running for > 1 day)

## Terraform Integration

A `null_resource` provisioner in `terraform/modules/fabric/main.tf` prints a reminder
to configure this OneLake mirror after `terraform apply`:

```hcl
resource "null_resource" "onelake_mirror_setup_reminder" {
  depends_on = [azapi_resource.fabric_capacity]
  provisioner "local-exec" {
    command = "echo 'ACTION REQUIRED: Configure Activity Log OneLake mirror for AUDIT-003 compliance. See services/detection-plane/docs/AUDIT-003-onelake-setup.md. Retention must be >= 2 years (730 days).'"
  }
}
```

## Compliance Checklist

- [ ] OneLake shortcut or Data Pipeline is configured and active
- [ ] Activity Log data appears in OneLake lakehouse within 5 minutes of source event
- [ ] Retention policy is set to >= 730 days (2 years minimum per AUDIT-003)
- [ ] Retention configuration verified via table properties or Spark SQL
- [ ] KQL query against OneLake `ActivityLog` returns recent events
