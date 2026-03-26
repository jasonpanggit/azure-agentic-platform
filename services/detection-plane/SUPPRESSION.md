# Alert Suppression Rules (DETECT-007)

## How It Works

Azure Monitor **processing rules** (formerly "action rules") suppress alerts
before they trigger Action Groups. When a processing rule suppresses an alert:

1. The alert fires in Azure Monitor but the Action Group is **not invoked**.
2. The alert **never reaches Event Hub** (the Action Group event hub receiver is suppressed).
3. Therefore, it **never enters `RawAlerts`**, `EnrichedAlerts`, or `DetectionResults`.
4. No Cosmos DB incident record is created.
5. No agent thread is spawned.

**This is inherent behavior** — no code is required in the detection plane.
Suppression happens upstream at the Azure Monitor Action Group level.

## Verification Procedure (Manual)

1. Create an Azure Monitor processing rule suppressing a specific alert class:
   ```bash
   az monitor alert-processing-rule create \
     --name "suppress-test-rule" \
     --resource-group "rg-aap-dev" \
     --rule-type RemoveAllActionGroups \
     --scopes "/subscriptions/{sub-id}" \
     --filter-alert-rule-name Equals "TestSuppressedRule"
   ```

2. Fire a matching alert.

3. Wait 60 seconds.

4. Assert: No record in `DetectionResults` (query Eventhouse).

5. Assert: No incident record in Cosmos DB.

6. Remove the suppression rule:
   ```bash
   az monitor alert-processing-rule delete \
     --name "suppress-test-rule" \
     --resource-group "rg-aap-dev"
   ```

7. Fire the same alert again.

8. Assert: `DetectionResults` row exists with correct domain.

9. Assert: Cosmos DB incident record created.

## Why No Code Is Needed

The AAP detection plane receives alerts exclusively via Event Hub.
Event Hub receives alerts exclusively from Azure Monitor Action Groups.
If a processing rule suppresses the Action Group, the event never reaches
Event Hub, and the entire downstream pipeline (Eventhouse → Activator → API Gateway)
is naturally bypassed.

This is the correct architectural behavior: suppression is a platform-level concern
managed by Azure Monitor, not a detection-plane concern.
