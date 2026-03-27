---
title: "VM Extension Install Failure"
domain: compute
version: "1.0"
tags: ["vm", "extension", "provisioning", "agent", "custom-script"]
---

## Symptoms

A VM extension (Custom Script Extension, Monitoring Agent, DSC, or Antimalware) fails to install or execute on a Virtual Machine. The VM provisioning state shows "Failed" or "ProvisioningState/failed" for the extension. Azure Activity Log shows an extension operation error. The VM itself may be running correctly but lacks the required agent functionality.

## Root Causes

1. VM Agent not running or outdated — the extension host service is down or too old to process the extension.
2. Network connectivity issue — the VM cannot reach the Azure extension endpoint (`*.blob.core.windows.net` or `*.windowsazure.com`) due to NSG rules.
3. Extension script error — the custom script or DSC configuration contains a syntax error or an unavailable dependency.
4. Concurrent extension operations — another extension is already installing and the new one cannot proceed.

## Diagnostic Steps

1. Check extension status and last error message:
   ```bash
   az vm extension list --resource-group {rg} --vm-name {vm_name} \
     --query "[].{name:name,state:provisioningState,message:instanceView.statuses[-1].message}" \
     --output table
   ```
2. Get detailed extension instance view with full error:
   ```bash
   az vm get-instance-view --resource-group {rg} --name {vm_name} \
     --query "instanceView.extensions[?name=='{ext_name}'].statuses"
   ```
3. Check VM Agent status:
   ```bash
   az vm get-instance-view --resource-group {rg} --name {vm_name} \
     --query "instanceView.vmAgent.{status:statuses[0].displayStatus,version:vmAgentVersion}"
   ```
4. Verify outbound connectivity to Azure services from the VM:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {vm_name} \
     --command-id RunShellScript \
     --scripts "curl -s -o /dev/null -w '%{http_code}' https://aka.ms/azcopyauto || echo FAILED"
   ```
5. Review extension logs inside the VM:
   ```bash
   az vm run-command invoke --resource-group {rg} --name {vm_name} \
     --command-id RunShellScript \
     --scripts "cat /var/log/azure/{ext_name}/*.log 2>/dev/null | tail -50"
   ```

## Remediation Commands

```bash
# Delete the failed extension and re-install
az vm extension delete --resource-group {rg} --vm-name {vm_name} --name {ext_name}

# Wait 60 seconds, then reinstall
sleep 60
az vm extension set \
  --resource-group {rg} \
  --vm-name {vm_name} \
  --name CustomScriptExtension \
  --publisher Microsoft.Compute \
  --version 1.10 \
  --settings '{"fileUris":["https://{storage}.blob.core.windows.net/{container}/{script}.sh"],"commandToExecute":"bash {script}.sh"}'

# Update VM agent on Linux
az vm run-command invoke --resource-group {rg} --name {vm_name} \
  --command-id RunShellScript \
  --scripts "waagent --version && sudo apt-get install -y waagent"
```

## Rollback Procedure

If the extension removal disrupted the VM configuration (e.g., a monitoring agent was removed), re-deploy the extension with the correct configuration after resolving the root cause. Check NSG rules to ensure port 443 outbound is allowed. If extension logs are unavailable due to disk issues, re-image the VM from a known-good image and re-apply the extension deployment configuration.
