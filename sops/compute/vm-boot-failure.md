---
title: "Azure VM — Boot Failure"
version: "1.0"
domain: compute
scenario_tags:
  - boot
  - startup
  - grub
  - bootloader
severity_threshold: P1
resource_types:
  - Microsoft.Compute/virtualMachines
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers Azure VM scenarios where the VM fails to boot, indicated by boot diagnostics showing
GRUB rescue, kernel panic, or OS startup failure.

## Pre-conditions
- VM is in running state but unresponsive OR health probes failing
- Boot diagnostics enabled

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_boot_diagnostics` to retrieve boot screenshot URI and serial log.
   - *Expected signal:* Login prompt visible in screenshot.
   - *Abnormal signal:* GRUB rescue screen, kernel panic, or Windows BSOD.

2. **[DIAGNOSTIC]** Call `query_activity_log` (4h look-back).
   - *Abnormal signal:* Recent OS disk swap or extension installation before failure.

3. **[DIAGNOSTIC]** Call `query_resource_health`.
   - *Abnormal signal:* Unavailable → possible host issue, not OS.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: {resource_name} boot failure detected. Serial log retrieved."
   - *Channels:* teams, email
   - *Severity:* critical

5. **[DECISION]** Root cause:
   - Cause A: OS update or kernel change broke boot
   - Cause B: File system corruption
   - Cause C: Disk missing or detached

## Remediation Steps

6. **[REMEDIATION:HIGH]** If Cause A: propose VM redeploy (repair disk offline).
   - This requires operator to attach OS disk to repair VM.
   - Call `propose_vm_redeploy` with reason="Boot failure — OS repair needed"
   - *Approval message:* "Approve redeploying {resource_name} for OS disk repair?"

## Escalation
- Boot failures often require manual disk repair — escalate to on-call with boot diagnostics screenshot

## Rollback
- Redeploy: irreversible

## References
- KB: https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/boot-error-troubleshoot
