from __future__ import annotations
"""Seed ~60 synthetic runbooks into PostgreSQL with Azure OpenAI embeddings.

Usage:
    python services/api-gateway/migrations/002_seed_runbooks.py

Requires:
    - POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD env vars
    - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY env vars (or DefaultAzureCredential)
    - EMBEDDING_DEPLOYMENT_NAME (default: text-embedding-3-small)
"""
import os

import os
import sys
import uuid
from datetime import datetime, timezone

import psycopg2
from openai import AzureOpenAI

EMBEDDING_MODEL = os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-small")

# Synthetic runbook definitions: (title, domain, content)
RUNBOOKS = [
    # Compute (10)
    ("VM High CPU Troubleshooting", "compute", "Step 1: Check Azure Monitor CPU metrics for the VM. Step 2: Identify top processes via Log Analytics (Perf | where CounterName == '% Processor Time'). Step 3: Check for recent deployments or config changes in Activity Log. Step 4: If caused by a known workload, consider scaling up the VM SKU. Step 5: If caused by a runaway process, restart the VM. Step 6: Set up CPU alert threshold at 85% for 5 minutes."),
    ("VM High Memory Usage", "compute", "Step 1: Query Log Analytics for Available MBytes metric. Step 2: Identify memory-hungry processes. Step 3: Check for memory leaks in application logs. Step 4: Consider adding swap or scaling VM size. Step 5: Restart affected services if memory fragmentation is suspected."),
    ("VM Disk Full Resolution", "compute", "Step 1: Check disk usage via Log Analytics InsightsMetrics. Step 2: Identify large files using du/df or WMI queries. Step 3: Clean temp files and old logs. Step 4: Expand the OS disk or add a data disk. Step 5: Set up disk usage alert at 90%."),
    ("VM Unresponsive Recovery", "compute", "Step 1: Check Azure Resource Health for platform issues. Step 2: Attempt serial console access. Step 3: Check boot diagnostics for OS-level errors. Step 4: If platform issue, wait for self-heal. Step 5: If OS-level, restart via Azure portal or CLI. Step 6: Redeploy to new host if persistent."),
    ("VMSS Scaling Failure", "compute", "Step 1: Check VMSS scaling history and Activity Log. Step 2: Verify quota availability in the region. Step 3: Check for ARM throttling (429 errors). Step 4: Validate VMSS model configuration. Step 5: Manually trigger scale-out if autoscale is stuck."),
    ("App Service 5xx Errors", "compute", "Step 1: Check Application Insights for exception telemetry. Step 2: Review App Service diagnostics blade. Step 3: Check for deployment-correlated errors. Step 4: Review memory and CPU metrics of the App Service plan. Step 5: Enable detailed error pages and check stderr logs."),
    ("Function App Timeout", "compute", "Step 1: Check Azure Functions monitor for invocation failures. Step 2: Verify function timeout configuration (default 5 min on Consumption). Step 3: Check for external dependency timeouts. Step 4: Consider Durable Functions for long-running tasks. Step 5: Move to Premium plan for extended timeout."),
    ("AKS Node NotReady", "compute", "Step 1: Check AKS node pool status via kubectl get nodes. Step 2: Describe the NotReady node for conditions. Step 3: Check kubelet logs via Container Insights. Step 4: Verify VM availability in Azure Resource Health. Step 5: Cordon and drain node, then delete for replacement."),
    ("Batch Job Failure", "compute", "Step 1: Check Azure Batch job status and task error messages. Step 2: Review task logs in the linked storage account. Step 3: Check for quota limits or pool sizing issues. Step 4: Verify container image availability. Step 5: Re-queue failed tasks."),
    ("VM Extension Install Failure", "compute", "Step 1: Check extension status via az vm extension list. Step 2: Review extension logs at /var/log/azure/ (Linux) or C:\\WindowsAzure\\Logs (Windows). Step 3: Check for conflicting extensions. Step 4: Remove and reinstall the extension. Step 5: Verify network connectivity to extension download URLs."),

    # Network (10)
    ("NSG Rule Misconfiguration", "network", "Step 1: List effective NSG rules for the affected NIC/subnet. Step 2: Compare against intended security policy. Step 3: Check for deny-all rules overriding allows. Step 4: Use IP flow verify to test connectivity. Step 5: Update NSG rules and verify with connectivity check."),
    ("Load Balancer Health Probe Failure", "network", "Step 1: Check LB health probe status in Azure portal. Step 2: Verify probe endpoint responds on the configured port. Step 3: Check backend pool instance health. Step 4: Review NSG rules between LB and backend. Step 5: Test connectivity from within the VNet."),
    ("DNS Resolution Failure", "network", "Step 1: Check Azure DNS zone configuration. Step 2: Verify DNS forwarder settings if using custom DNS. Step 3: Test resolution from within the VNet using nslookup. Step 4: Check for expired records. Step 5: Flush DNS cache on the client VM."),
    ("VPN Gateway Disconnect", "network", "Step 1: Check VPN gateway connection status. Step 2: Review connection logs for IKE/IPsec negotiation errors. Step 3: Verify shared key configuration on both ends. Step 4: Check for overlapping address spaces. Step 5: Reset the VPN gateway if connection is stuck."),
    ("Application Gateway 502 Errors", "network", "Step 1: Check backend health in App Gateway diagnostics. Step 2: Verify backend pool targets are healthy. Step 3: Check HTTP settings (port, protocol, probe path). Step 4: Review custom health probe response. Step 5: Check for SSL certificate issues."),
    ("ExpressRoute Circuit Down", "network", "Step 1: Check ExpressRoute circuit status in Azure portal. Step 2: Verify BGP peering state. Step 3: Contact connectivity provider if provider-provisioned. Step 4: Check for route advertisements. Step 5: Review Service Health for regional issues."),
    ("NIC Detached Recovery", "network", "Step 1: Identify the detached NIC in Azure portal. Step 2: Check VM status and associated NICs. Step 3: Reattach NIC to the VM. Step 4: Verify IP configuration after reattach. Step 5: Test network connectivity."),
    ("DDoS Attack Detected", "network", "Step 1: Check Azure DDoS Protection alerts. Step 2: Review attack metrics (inbound packets, bytes). Step 3: Verify DDoS Protection Standard is enabled. Step 4: Check mitigation policies. Step 5: Enable Azure Firewall or WAF for additional protection."),
    ("Peering Misconfiguration", "network", "Step 1: Verify VNet peering status (Connected, not Disconnected). Step 2: Check address space overlap. Step 3: Verify allow-forwarded-traffic and allow-gateway-transit settings. Step 4: Check route tables for correct next-hop. Step 5: Re-create peering if status is stuck."),
    ("Traffic Manager Failover", "network", "Step 1: Check Traffic Manager endpoint health status. Step 2: Review health check configuration (path, interval, failures). Step 3: Verify endpoint DNS resolves correctly. Step 4: Check for geographic routing misconfigurations. Step 5: Manually update endpoint priority if needed."),

    # Storage (10)
    ("Storage Account Throttling", "storage", "Step 1: Check Storage Analytics metrics for throttled requests. Step 2: Identify the throttled operation type (blob, queue, table). Step 3: Review ingress/egress limits for the account tier. Step 4: Implement retry with exponential backoff. Step 5: Consider upgrading to a higher performance tier or distributing across accounts."),
    ("Blob Access Denied", "storage", "Step 1: Check storage account access level (private, blob, container). Step 2: Verify SAS token validity and permissions. Step 3: Check RBAC assignments on the storage account. Step 4: Verify firewall and VNet rules allow the client IP. Step 5: Check if storage account key was rotated."),
    ("File Share Quota Exceeded", "storage", "Step 1: Check current file share usage vs quota. Step 2: Identify large files or directories consuming space. Step 3: Increase the quota (max 100 TiB for large file shares). Step 4: Archive old files to cool/archive tier. Step 5: Set up monitoring for quota usage at 80%."),
    ("Storage Replication Lag", "storage", "Step 1: Check Last Sync Time for GRS/RA-GRS accounts. Step 2: Review replication health in Azure portal. Step 3: Check for region-level issues via Service Health. Step 4: Verify RPO expectations match current lag. Step 5: Consider failover if lag exceeds acceptable threshold."),
    ("CORS Misconfiguration", "storage", "Step 1: Check CORS rules on the storage account. Step 2: Verify allowed origins match the requesting domain. Step 3: Check allowed methods (GET, PUT, POST). Step 4: Check exposed and allowed headers. Step 5: Test with curl and browser DevTools."),
    ("Lifecycle Management Failure", "storage", "Step 1: Check lifecycle management policy status. Step 2: Review policy rules for syntax errors. Step 3: Verify filter conditions (prefix, blob type). Step 4: Check execution logs for errors. Step 5: Manually apply the action to verify it works."),
    ("Data Lake Permission Error", "storage", "Step 1: Check ADLS Gen2 ACLs at the directory/file level. Step 2: Verify RBAC assignments (Storage Blob Data Contributor). Step 3: Check hierarchical namespace access control. Step 4: Review permission inheritance chain. Step 5: Use storage explorer to test access."),
    ("Queue Processing Backlog", "storage", "Step 1: Check queue message count and dequeue rate. Step 2: Identify bottleneck in processing application. Step 3: Scale up queue processors. Step 4: Check for poison messages in dead-letter queue. Step 5: Increase message visibility timeout if processing is slow."),
    ("Table Storage Timeout", "storage", "Step 1: Check Storage Analytics for latency metrics. Step 2: Review partition key design for hotspot patterns. Step 3: Consider batch operations for multiple inserts. Step 4: Implement retry with backoff. Step 5: Consider migrating to Cosmos DB Table API for better performance."),
    ("Disk Snapshot Failure", "storage", "Step 1: Check snapshot creation status in Activity Log. Step 2: Verify snapshot quota hasn't been exceeded. Step 3: Check if the source disk is in a consistent state. Step 4: Retry snapshot creation. Step 5: Use incremental snapshots to reduce failure risk."),

    # Security (10)
    ("Key Vault Access Denied", "security", "Step 1: Check Key Vault access policy or RBAC permissions. Step 2: Verify the caller identity (managed identity, service principal). Step 3: Check Key Vault firewall rules and VNet restrictions. Step 4: Review Key Vault diagnostic logs. Step 5: Grant the minimum required permission (get, list, set)."),
    ("Defender Alert Critical", "security", "Step 1: Review the Defender for Cloud alert details and severity. Step 2: Identify affected resources and attack vector. Step 3: Follow the recommended remediation steps. Step 4: Check for lateral movement indicators. Step 5: Isolate affected resources if compromise is confirmed."),
    ("Unauthorized Access Attempt", "security", "Step 1: Review sign-in logs in Entra ID. Step 2: Check for compromised credentials. Step 3: Enable MFA if not already active. Step 4: Review conditional access policies. Step 5: Block the suspicious IP address in NSG or WAF."),
    ("Certificate Expiry Imminent", "security", "Step 1: List certificates with upcoming expiry in Key Vault. Step 2: Check auto-renewal settings. Step 3: Generate a new certificate or import a renewed one. Step 4: Update references in App Service, App Gateway, or API Management. Step 5: Set up Key Vault certificate expiry alerts."),
    ("RBAC Misconfiguration", "security", "Step 1: List all role assignments for the affected scope. Step 2: Identify overly permissive assignments (Owner, Contributor). Step 3: Apply principle of least privilege. Step 4: Use custom roles for fine-grained control. Step 5: Review with Azure AD Privileged Identity Management."),
    ("Managed Identity Failure", "security", "Step 1: Verify managed identity is enabled on the resource. Step 2: Check RBAC assignments for the managed identity object ID. Step 3: Test token acquisition with curl to IMDS endpoint. Step 4: Check for identity propagation delays (up to 10 min). Step 5: Delete and recreate if stuck."),
    ("Network Exposure Detected", "security", "Step 1: Review Defender for Cloud network exposure alert. Step 2: Check public IP assignments and NSG rules. Step 3: Remove unnecessary public IPs. Step 4: Enable private endpoints for exposed services. Step 5: Apply JIT access if SSH/RDP is needed."),
    ("Encryption Key Rotation Failure", "security", "Step 1: Check Key Vault key version history. Step 2: Verify auto-rotation policy. Step 3: Check linked resources using customer-managed keys. Step 4: Manually rotate the key. Step 5: Verify all dependent resources pick up the new version."),
    ("Compliance Violation Detected", "security", "Step 1: Review Azure Policy compliance report. Step 2: Identify the specific policy that is violated. Step 3: Assess the impact and risk of the violation. Step 4: Remediate the resource to meet policy requirements. Step 5: Request an exemption if remediation is not feasible."),
    ("Secret Exposure in Repository", "security", "Step 1: Immediately rotate the exposed secret. Step 2: Review commit history for the exposure timeline. Step 3: Check audit logs for unauthorized use. Step 4: Update all applications using the secret. Step 5: Enable GitHub secret scanning and Key Vault references."),

    # Arc (10)
    ("Arc Server Disconnected", "arc", "Step 1: Check Azure Arc agent status on the server (azcmagent show). Step 2: Verify network connectivity to Azure endpoints. Step 3: Check proxy settings if behind a proxy. Step 4: Review azcmagent logs (/var/opt/azcmagent/log/). Step 5: Restart the himds service. Step 6: Reconnect with azcmagent connect if expired."),
    ("Arc Agent Version Outdated", "arc", "Step 1: Check current agent version with azcmagent version. Step 2: Compare against the latest version in Azure docs. Step 3: Plan upgrade window. Step 4: Update via package manager (apt/yum) or extension manager. Step 5: Verify post-upgrade connectivity."),
    ("Arc Extension Install Failure", "arc", "Step 1: Check extension status via az connectedmachine extension list. Step 2: Review extension logs. Step 3: Verify network access to extension download URLs. Step 4: Check for conflicting extensions. Step 5: Remove and reinstall the extension."),
    ("Arc Policy Compliance Drift", "arc", "Step 1: Check Azure Policy guest configuration results. Step 2: Identify non-compliant settings. Step 3: Review machine configuration assignments. Step 4: Apply corrective configuration. Step 5: Wait for policy re-evaluation or trigger manual scan."),
    ("Arc GitOps Reconciliation Failure", "arc", "Step 1: Check Flux configuration status via az k8s-configuration flux show. Step 2: Review Flux logs for reconciliation errors. Step 3: Check source repository accessibility. Step 4: Verify Kustomization paths are correct. Step 5: Force reconciliation with flux reconcile."),
    ("Arc K8s Node NotReady", "arc", "Step 1: Check Arc-connected cluster node status. Step 2: Describe NotReady node for conditions. Step 3: Check kubelet and Arc agent health. Step 4: Verify on-premises infrastructure health. Step 5: Cordon, drain, and investigate the node."),
    ("Arc Data Service Unavailable", "arc", "Step 1: Check Arc data controller status. Step 2: Verify SQL MI or PostgreSQL pod health. Step 3: Check persistent volume claims. Step 4: Review controller logs. Step 5: Restart the data service pod."),
    ("Hybrid Connectivity Lost", "arc", "Step 1: Check Azure Arc connectivity status for all affected servers. Step 2: Verify on-premises network infrastructure. Step 3: Test DNS resolution of Azure endpoints. Step 4: Check firewall rules for required URLs. Step 5: Re-establish connectivity one server at a time."),
    ("Arc Guest Configuration Failure", "arc", "Step 1: Check guest configuration extension status. Step 2: Review compliance report in Azure portal. Step 3: Check for DSC configuration conflicts. Step 4: Verify policy assignments. Step 5: Redeploy guest configuration extension."),
    ("Arc Enrollment Error", "arc", "Step 1: Verify Azure subscription registration for Arc providers. Step 2: Check resource group permissions. Step 3: Verify azcmagent connect parameters. Step 4: Check for proxy or firewall blocking enrollment. Step 5: Review azcmagent logs for detailed error."),

    # SRE (10)
    ("Alert Storm Detection and Mitigation", "sre", "Step 1: Identify the alert storm pattern (same rule, multiple resources). Step 2: Check for common root cause (network outage, deployment). Step 3: Create a temporary suppression rule for duplicate alerts. Step 4: Focus triage on the root cause. Step 5: Remove suppression rule after resolution."),
    ("Cascading Failure Analysis", "sre", "Step 1: Map the dependency chain of affected services. Step 2: Identify the initiating failure point. Step 3: Check for circuit breaker activation. Step 4: Restore services in dependency order (bottom-up). Step 5: Document the cascade path for future mitigation."),
    ("Resource Quota Exhaustion", "sre", "Step 1: Check subscription quota usage for the affected resource type. Step 2: Identify which resources are consuming quota. Step 3: Request quota increase via support ticket. Step 4: Consider right-sizing existing resources. Step 5: Set up quota usage alerts at 80%."),
    ("Deployment Rollback Procedure", "sre", "Step 1: Identify the failing deployment. Step 2: Check deployment history for the last known good state. Step 3: Initiate rollback to previous version. Step 4: Verify service health after rollback. Step 5: Investigate root cause before re-deploying."),
    ("Change-Caused Incident Analysis", "sre", "Step 1: Query Activity Log for changes in the prior 2 hours. Step 2: Correlate change timestamps with incident start time. Step 3: Identify the specific change that caused the issue. Step 4: Revert the change if possible. Step 5: Document as a change-caused incident."),
    ("Monitoring Gap Detection", "sre", "Step 1: Review alert rules coverage for the affected resource type. Step 2: Identify missing metrics or log collection. Step 3: Deploy missing Azure Monitor agent or diagnostic settings. Step 4: Create alert rules for the identified gap. Step 5: Test alerts with synthetic load."),
    ("Incident Correlation Workflow", "sre", "Step 1: Collect all related alerts within the time window. Step 2: Group by affected resources and subscriptions. Step 3: Identify shared infrastructure dependencies. Step 4: Assign a single incident ID for correlated alerts. Step 5: Route to the domain with the root cause."),
    ("Capacity Planning Trigger", "sre", "Step 1: Review resource utilization trends over the past 30 days. Step 2: Identify resources approaching capacity thresholds. Step 3: Forecast growth based on historical patterns. Step 4: Create scaling recommendations. Step 5: Schedule capacity increases before thresholds are hit."),
    ("Cross-Domain Performance Degradation", "sre", "Step 1: Identify all affected services and their domains. Step 2: Map the request flow across domains. Step 3: Check each domain's metrics for anomalies. Step 4: Identify the bottleneck domain. Step 5: Route to the domain specialist for targeted investigation."),
    ("Service Dependency Failure", "sre", "Step 1: Identify the failed dependency from application traces. Step 2: Check Azure Service Health for platform issues. Step 3: Test connectivity to the dependency endpoint. Step 4: Check for DNS, certificate, or authentication issues. Step 5: Implement fallback or circuit breaker pattern."),
]


def get_embedding(client: AzureOpenAI, text: str) -> list[float]:
    """Generate embedding vector for the given text."""
    response = client.embeddings.create(
        input=[text],
        model=EMBEDDING_MODEL,
    )
    return response.data[0].embedding


def main():
    """Seed runbooks into PostgreSQL with embeddings."""
    # Connect to PostgreSQL
    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        port=os.environ.get("POSTGRES_PORT", "5432"),
    )

    # Connect to Azure OpenAI
    openai_client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version="2024-06-01",
    )

    cursor = conn.cursor()

    print(f"Seeding {len(RUNBOOKS)} runbooks...")
    for i, (title, domain, content) in enumerate(RUNBOOKS):
        # Generate embedding
        embed_text = f"{title}\n{content}"
        embedding = get_embedding(openai_client, embed_text)

        # Insert into PostgreSQL
        cursor.execute(
            """
            INSERT INTO runbooks (id, title, domain, version, content, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                str(uuid.uuid5(uuid.NAMESPACE_DNS, f"runbook-{domain}-{i}")),
                title,
                domain,
                "1.0",
                content,
                embedding,
            ),
        )
        print(f"  [{i+1}/{len(RUNBOOKS)}] {title} ({domain})")

    conn.commit()
    cursor.close()
    conn.close()
    print(f"Done. {len(RUNBOOKS)} runbooks seeded.")


if __name__ == "__main__":
    main()
