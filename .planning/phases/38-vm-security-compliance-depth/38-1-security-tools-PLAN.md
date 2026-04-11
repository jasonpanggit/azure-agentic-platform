---
plan: 38-1
title: "Security Tools — 5 new @ai_function tools in tools.py + requirements.txt"
wave: 1
modifies:
  - agents/compute/tools.py
  - agents/compute/requirements.txt
depends_on: []
must_haves:
  - query_defender_tvm_cve_count exists with @ai_function decorator
  - vm_risk_score key present in query_defender_tvm_cve_count return dict
  - query_jit_access_status exists with @ai_function decorator
  - jit_enabled bool key present in query_jit_access_status return dict
  - query_effective_nsg_rules exists with @ai_function decorator
  - effective_rules list key present in query_effective_nsg_rules return dict
  - query_backup_rpo exists with @ai_function decorator
  - backup_enabled bool key present in query_backup_rpo return dict
  - query_asr_replication_health exists with @ai_function decorator
  - asr_enabled bool key present in query_asr_replication_health return dict
  - requirements.txt contains azure-mgmt-security>=7.0.0
  - requirements.txt contains azure-mgmt-network>=23.0.0
  - requirements.txt contains azure-mgmt-recoveryservicesbackup>=9.0.0
  - requirements.txt contains azure-mgmt-recoveryservicessiterecovery>=1.0.0
---

# Plan 38-1: Security Tools

## Goal

Add 5 new `@ai_function` tools to `agents/compute/tools.py` that make per-VM
security posture a first-class diagnostic signal. Update `requirements.txt` with
the 4 new SDK packages needed.

---

## Read First

<read_first>
- `agents/compute/tools.py` — lines 1–120 (lazy import block + _log_sdk_availability pattern)
- `agents/compute/tools.py` — lines 785–895 (query_boot_diagnostics + query_vm_sku_options: exact start_time / instrument_tool_call / try-except-never-raise pattern)
- `agents/compute/tools.py` — lines 2680–2690 (end of file — append new tools after detect_performance_drift)
- `agents/compute/requirements.txt` — full file (confirm existing packages before adding)
- `agents/security/tools.py` — lines 28–57 (SecurityCenter + NetworkManagementClient lazy import patterns)
- `.planning/phases/38-vm-security-compliance-depth/38-CONTEXT.md` — full file (decisions section)
</read_first>

---

## Acceptance Criteria

```bash
# 5 tools exist with @ai_function decorator
grep -c "@ai_function" agents/compute/tools.py
# Must be >= 33 (28 existing + 5 new)

# Key fields in return shapes
grep "vm_risk_score" agents/compute/tools.py       # >= 1 match
grep "jit_enabled" agents/compute/tools.py         # >= 1 match
grep "effective_rules" agents/compute/tools.py     # >= 1 match
grep "backup_enabled" agents/compute/tools.py      # >= 1 match
grep "asr_enabled" agents/compute/tools.py         # >= 1 match

# New packages in requirements.txt
grep "azure-mgmt-security" agents/compute/requirements.txt
grep "azure-mgmt-network" agents/compute/requirements.txt
grep "azure-mgmt-recoveryservicesbackup" agents/compute/requirements.txt
grep "azure-mgmt-recoveryservicessiterecovery" agents/compute/requirements.txt
```

---

## Action

### Step 1 — Update `agents/compute/requirements.txt`

Add these 4 lines (azure-mgmt-resourcegraph already present at `>=8.0.1`):

```
azure-mgmt-security>=7.0.0
azure-mgmt-network>=23.0.0
azure-mgmt-recoveryservicesbackup>=9.0.0
azure-mgmt-recoveryservicessiterecovery>=1.0.0
```

Note: `azure-mgmt-resourcegraph` is already present (`>=8.0.1`) — do NOT add a
duplicate. Verify `azure-mgmt-compute` is present (already `>=30.0.0`) — also not
duplicated. `azure-mgmt-network` may already exist (security agent uses it) —
check before adding.

---

### Step 2 — Add lazy imports to `agents/compute/tools.py`

Append these 4 import blocks immediately after the existing
`ForecasterClient` import block (around line 81), before
`from shared.approval_manager import create_approval_record`:

```python
# Lazy import — azure-mgmt-security may not be installed in all envs
try:
    from azure.mgmt.security import SecurityCenter
except ImportError:
    SecurityCenter = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-network may not be installed in all envs
try:
    from azure.mgmt.network import NetworkManagementClient
except ImportError:
    NetworkManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-recoveryservicesbackup may not be installed in all envs
try:
    from azure.mgmt.recoveryservicesbackup import RecoveryServicesBackupClient
except ImportError:
    RecoveryServicesBackupClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-recoveryservicessiterecovery may not be installed in all envs
try:
    from azure.mgmt.recoveryservicessiterecovery import SiteRecoveryManagementClient
except ImportError:
    SiteRecoveryManagementClient = None  # type: ignore[assignment,misc]
```

Also add these 4 packages to `_log_sdk_availability()` dict:

```python
"azure-mgmt-security": "azure.mgmt.security",
"azure-mgmt-network": "azure.mgmt.network",
"azure-mgmt-recoveryservicesbackup": "azure.mgmt.recoveryservicesbackup",
"azure-mgmt-recoveryservicessiterecovery": "azure.mgmt.recoveryservicessiterecovery",
```

---

### Step 3 — Append 5 new tool functions (after `detect_performance_drift`)

Append all 5 functions at the end of `agents/compute/tools.py` in this order:

---

#### Tool 1: `query_defender_tvm_cve_count`

```python
@ai_function
def query_defender_tvm_cve_count(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query Defender Threat & Vulnerability Management CVE counts for a VM.

    Uses Azure Resource Graph to query SecurityResources for assessments
    targeting this VM, grouped by severity. Returns a vm_risk_score computed
    as: critical×10 + high×5 + medium×2 + low×1 for easy LLM comparison.

    Args:
        resource_group: Resource group containing the VM.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with keys:
            vm_name (str): VM name queried.
            resource_group (str): Resource group.
            subscription_id (str): Subscription ID.
            critical (int): Critical CVE count.
            high (int): High CVE count.
            medium (int): Medium CVE count.
            low (int): Low CVE count.
            total (int): Total CVE count.
            vm_risk_score (float): Weighted risk score (critical×10 + high×5 + medium×2 + low×1).
            query_status (str): "success" or "error".
            duration_ms (int): Query duration in milliseconds.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_defender_tvm_cve_count",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if ResourceGraphClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-resourcegraph not installed",
                    "vm_name": vm_name,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            client = ResourceGraphClient(credential)

            # Build VM resource ID to filter assessments
            vm_resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
            ).lower()

            kql = f"""
SecurityResources
| where type == "microsoft.security/assessments"
| where tolower(properties.resourceDetails.Id) startswith "{vm_resource_id}"
| where properties.status.code == "Unhealthy"
| extend severity = tostring(properties.metadata.severity)
| summarize count() by severity
"""
            query_req = QueryRequest(
                subscriptions=[subscription_id],
                query=kql,
                options=QueryRequestOptions(result_format="objectArray"),
            )
            response = client.resources(query_req)

            severity_counts: Dict[str, int] = {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            }
            for row in (response.data or []):
                sev = str(row.get("severity", "")).lower()
                count = int(row.get("count_", row.get("count", 0)))
                if sev in severity_counts:
                    severity_counts[sev] += count

            total = sum(severity_counts.values())
            vm_risk_score = float(
                severity_counts["critical"] * 10
                + severity_counts["high"] * 5
                + severity_counts["medium"] * 2
                + severity_counts["low"] * 1
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_defender_tvm_cve_count: complete | vm=%s total=%d risk_score=%.1f duration_ms=%d",
                vm_name, total, vm_risk_score, duration_ms,
            )
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "critical": severity_counts["critical"],
                "high": severity_counts["high"],
                "medium": severity_counts["medium"],
                "low": severity_counts["low"],
                "total": total,
                "vm_risk_score": vm_risk_score,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_defender_tvm_cve_count error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```

---

#### Tool 2: `query_jit_access_status`

```python
@ai_function
def query_jit_access_status(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query JIT (Just-In-Time) access policy status and active sessions for a VM.

    Uses azure-mgmt-security JitNetworkAccessPoliciesOperations to check whether
    JIT is configured for the VM's resource group and whether any sessions are
    currently active. Returns a graceful "not configured" response if JIT is not
    enabled for this VM — this is not treated as an error.

    Args:
        resource_group: Resource group containing the VM.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with keys:
            vm_name (str): VM name queried.
            resource_group (str): Resource group.
            subscription_id (str): Subscription ID.
            jit_enabled (bool): Whether JIT policy is configured for this VM.
            policy_name (str): JIT policy name, or "" if not configured.
            allowed_ports (list): List of dicts with port, protocol, maxDuration.
            active_sessions (list): List of active JIT session dicts.
            query_status (str): "success" or "error".
            duration_ms (int): Query duration in milliseconds.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_jit_access_status",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if SecurityCenter is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-security not installed",
                    "vm_name": vm_name,
                    "jit_enabled": False,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            # SecurityCenter requires a subscription_id and asc_location;
            # location is derived from the resource group location or defaults to "eastus".
            # We use list() to enumerate policies in the resource group.
            client = SecurityCenter(credential, subscription_id, asc_location="eastus")

            vm_resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
            ).lower()

            jit_enabled = False
            policy_name = ""
            allowed_ports: List[Dict[str, Any]] = []
            active_sessions: List[Dict[str, Any]] = []

            for policy in client.jit_network_access_policies.list_by_resource_group(
                resource_group
            ):
                for vm_entry in getattr(policy, "virtual_machines", None) or []:
                    entry_id = str(getattr(vm_entry, "id", "")).lower()
                    if entry_id == vm_resource_id:
                        jit_enabled = True
                        policy_name = policy.name or ""
                        for port_cfg in getattr(vm_entry, "ports", None) or []:
                            allowed_ports.append({
                                "port": getattr(port_cfg, "number", 0),
                                "protocol": getattr(port_cfg, "protocol", "*"),
                                "max_request_access_duration": getattr(
                                    port_cfg, "max_request_access_duration", ""
                                ),
                            })
                        # Active requests (pending/approved) for this VM
                        for req in getattr(policy, "requests", None) or []:
                            for req_vm in getattr(req, "virtual_machines", None) or []:
                                req_vm_id = str(getattr(req_vm, "id", "")).lower()
                                if req_vm_id == vm_resource_id:
                                    active_sessions.append({
                                        "requestor": getattr(req, "requestor", ""),
                                        "start_time": str(
                                            getattr(req, "start_time_utc", "")
                                        ),
                                        "justification": getattr(req, "justification", ""),
                                    })
                        break
                if jit_enabled:
                    break

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_jit_access_status: complete | vm=%s jit_enabled=%s duration_ms=%d",
                vm_name, jit_enabled, duration_ms,
            )
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "jit_enabled": jit_enabled,
                "policy_name": policy_name,
                "allowed_ports": allowed_ports,
                "active_sessions": active_sessions,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_jit_access_status error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "jit_enabled": False,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```

---

#### Tool 3: `query_effective_nsg_rules`

```python
@ai_function
def query_effective_nsg_rules(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query effective NSG rules at the NIC level for a VM.

    Retrieves the VM's primary NIC via azure-mgmt-compute, then calls
    network_interfaces.list_effective_network_security_groups() for the
    actual evaluated rules (including inherited subnet NSG rules).

    Rules with priority < 200 are flagged as "high_priority" since these
    typically indicate manual overrides or emergency rules.

    Args:
        resource_group: Resource group containing the VM.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with keys:
            vm_name (str): VM name queried.
            resource_group (str): Resource group.
            subscription_id (str): Subscription ID.
            nic_name (str): Primary NIC name resolved.
            effective_rules (list): List of rule dicts with name, direction, access,
                priority, protocol, source_port_range, destination_port_range,
                high_priority (bool: priority < 200).
            inbound_deny_count (int): Count of inbound Deny rules.
            outbound_deny_count (int): Count of outbound Deny rules.
            high_priority_count (int): Count of rules with priority < 200.
            query_status (str): "success" or "error".
            duration_ms (int): Query duration in milliseconds.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_effective_nsg_rules",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if ComputeManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-compute not installed",
                    "vm_name": vm_name,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }
            if NetworkManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-network not installed",
                    "vm_name": vm_name,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            compute_client = ComputeManagementClient(credential, subscription_id)
            network_client = NetworkManagementClient(credential, subscription_id)

            # Resolve primary NIC from VM
            vm = compute_client.virtual_machines.get(resource_group, vm_name)
            nics = getattr(vm, "network_profile", None)
            nic_id = ""
            nic_name = ""
            for nic_ref in (getattr(nics, "network_interfaces", None) or []):
                nic_id = getattr(nic_ref, "id", "") or ""
                # Extract NIC name from resource ID
                nic_name = nic_id.split("/")[-1] if nic_id else ""
                break  # Use first (primary) NIC

            if not nic_name:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "vm_name": vm_name,
                    "resource_group": resource_group,
                    "subscription_id": subscription_id,
                    "nic_name": "",
                    "effective_rules": [],
                    "inbound_deny_count": 0,
                    "outbound_deny_count": 0,
                    "high_priority_count": 0,
                    "query_status": "success",
                    "duration_ms": duration_ms,
                }

            # Get effective NSG rules — this is a long-running operation (LRO)
            poller = network_client.network_interfaces.begin_list_effective_network_security_groups(
                resource_group, nic_name
            )
            result = poller.result()

            effective_rules: List[Dict[str, Any]] = []
            inbound_deny = 0
            outbound_deny = 0
            high_priority_count = 0

            for nsg_assoc in (getattr(result, "value", None) or []):
                for rule in (getattr(nsg_assoc, "effective_security_rules", None) or []):
                    name = getattr(rule, "name", "") or ""
                    direction = getattr(rule, "direction", "") or ""
                    access = getattr(rule, "access", "") or ""
                    priority = int(getattr(rule, "priority", 65000) or 65000)
                    protocol = getattr(rule, "protocol", "") or ""
                    src_port = getattr(rule, "source_port_range", "") or ""
                    dst_port = getattr(rule, "destination_port_range", "") or ""

                    high_priority = priority < 200
                    rule_dict = {
                        "name": name,
                        "direction": direction,
                        "access": access,
                        "priority": priority,
                        "protocol": protocol,
                        "source_port_range": src_port,
                        "destination_port_range": dst_port,
                        "high_priority": high_priority,
                    }
                    effective_rules.append(rule_dict)

                    if access.lower() == "deny":
                        if direction.lower() == "inbound":
                            inbound_deny += 1
                        elif direction.lower() == "outbound":
                            outbound_deny += 1
                    if high_priority:
                        high_priority_count += 1

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_effective_nsg_rules: complete | vm=%s nic=%s rules=%d duration_ms=%d",
                vm_name, nic_name, len(effective_rules), duration_ms,
            )
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "nic_name": nic_name,
                "effective_rules": effective_rules,
                "inbound_deny_count": inbound_deny,
                "outbound_deny_count": outbound_deny,
                "high_priority_count": high_priority_count,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_effective_nsg_rules error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```

---

#### Tool 4: `query_backup_rpo`

```python
@ai_function
def query_backup_rpo(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query Azure Backup last backup time and RPO status for a VM.

    Uses azure-mgmt-resourcegraph to find Recovery Services vaults in the
    subscription, then queries azure-mgmt-recoveryservicesbackup for protected
    items matching this VM. Returns a graceful "not configured" response if no
    vault or backup policy is found — this is not treated as an error.

    Args:
        resource_group: Resource group containing the VM.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with keys:
            vm_name (str): VM name queried.
            resource_group (str): Resource group.
            subscription_id (str): Subscription ID.
            backup_enabled (bool): Whether Azure Backup is configured for this VM.
            vault_name (str): Recovery Services vault name, or "" if not configured.
            vault_resource_group (str): Vault resource group, or "" if not configured.
            last_backup_time (str): ISO 8601 timestamp of last backup, or "" if none.
            last_backup_status (str): Last backup job status (e.g., "Completed"), or "".
            rpo_minutes (int): Minutes since last successful backup (RPO proxy), or -1.
            query_status (str): "success" or "error".
            duration_ms (int): Query duration in milliseconds.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_backup_rpo",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if ResourceGraphClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-resourcegraph not installed",
                    "vm_name": vm_name,
                    "backup_enabled": False,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }
            if RecoveryServicesBackupClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-recoveryservicesbackup not installed",
                    "vm_name": vm_name,
                    "backup_enabled": False,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()

            # Step 1: Find Recovery Services vaults via ARG
            arg_client = ResourceGraphClient(credential)
            vault_query = QueryRequest(
                subscriptions=[subscription_id],
                query=(
                    "Resources "
                    "| where type == 'microsoft.recoveryservices/vaults' "
                    "| project name, resourceGroup, location"
                ),
                options=QueryRequestOptions(result_format="objectArray"),
            )
            vault_response = arg_client.resources(vault_query)
            vaults = list(vault_response.data or [])

            if not vaults:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                logger.info("query_backup_rpo: no vaults found | vm=%s", vm_name)
                return {
                    "vm_name": vm_name,
                    "resource_group": resource_group,
                    "subscription_id": subscription_id,
                    "backup_enabled": False,
                    "vault_name": "",
                    "vault_resource_group": "",
                    "last_backup_time": "",
                    "last_backup_status": "",
                    "rpo_minutes": -1,
                    "query_status": "success",
                    "duration_ms": duration_ms,
                }

            # Step 2: Search each vault for a protected item matching the VM
            backup_client = RecoveryServicesBackupClient(credential, subscription_id)
            vm_resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
            ).lower()

            for vault in vaults:
                vault_name = vault.get("name", "")
                vault_rg = vault.get("resourceGroup", "")
                if not vault_name or not vault_rg:
                    continue
                try:
                    items = backup_client.backup_protected_items.list(
                        vault_name=vault_name,
                        resource_group_name=vault_rg,
                        filter=(
                            f"backupManagementType eq 'AzureIaasVM' "
                            f"and itemType eq 'VM'"
                        ),
                    )
                    for item in items:
                        props = getattr(item, "properties", None)
                        source_id = str(
                            getattr(props, "virtual_machine_id", "") or ""
                        ).lower()
                        if source_id == vm_resource_id:
                            last_backup_raw = getattr(
                                props, "last_backup_time", None
                            )
                            last_backup_str = (
                                last_backup_raw.isoformat()
                                if hasattr(last_backup_raw, "isoformat")
                                else str(last_backup_raw or "")
                            )
                            last_backup_status = str(
                                getattr(props, "last_backup_status", "") or ""
                            )
                            # Compute RPO in minutes
                            rpo_minutes = -1
                            if last_backup_raw and hasattr(last_backup_raw, "tzinfo"):
                                delta = datetime.now(timezone.utc) - last_backup_raw.replace(
                                    tzinfo=timezone.utc
                                    if last_backup_raw.tzinfo is None
                                    else last_backup_raw.tzinfo
                                )
                                rpo_minutes = int(delta.total_seconds() / 60)

                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            logger.info(
                                "query_backup_rpo: found | vm=%s vault=%s rpo_min=%d duration_ms=%d",
                                vm_name, vault_name, rpo_minutes, duration_ms,
                            )
                            return {
                                "vm_name": vm_name,
                                "resource_group": resource_group,
                                "subscription_id": subscription_id,
                                "backup_enabled": True,
                                "vault_name": vault_name,
                                "vault_resource_group": vault_rg,
                                "last_backup_time": last_backup_str,
                                "last_backup_status": last_backup_status,
                                "rpo_minutes": rpo_minutes,
                                "query_status": "success",
                                "duration_ms": duration_ms,
                            }
                except Exception:
                    # Swallow per-vault errors and continue to next vault
                    continue

            # No protected item found across all vaults
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info("query_backup_rpo: vm not protected | vm=%s", vm_name)
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "backup_enabled": False,
                "vault_name": "",
                "vault_resource_group": "",
                "last_backup_time": "",
                "last_backup_status": "",
                "rpo_minutes": -1,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_backup_rpo error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "backup_enabled": False,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```

---

#### Tool 5: `query_asr_replication_health`

```python
@ai_function
def query_asr_replication_health(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    thread_id: str,
) -> Dict[str, Any]:
    """Query Azure Site Recovery replication health for a VM.

    Uses azure-mgmt-resourcegraph to find ASR (Recovery Services) vaults with
    site recovery capability, then queries ReplicationProtectedItemsOperations
    for the VM. Returns a graceful "not configured" response if ASR is not
    enabled for this VM — this is not treated as an error.

    Args:
        resource_group: Resource group containing the VM.
        vm_name: Virtual machine name.
        subscription_id: Azure subscription ID.
        thread_id: Foundry thread ID.

    Returns:
        Dict with keys:
            vm_name (str): VM name queried.
            resource_group (str): Resource group.
            subscription_id (str): Subscription ID.
            asr_enabled (bool): Whether ASR replication is configured for this VM.
            vault_name (str): ASR vault name, or "" if not configured.
            replication_health (str): Health state (e.g. "Normal", "Warning", "Critical",
                "not_configured").
            failover_readiness (str): Failover readiness state (e.g. "Ready", "NotReady").
            rpo_seconds (int): Current RPO in seconds, or -1 if not available.
            primary_fabric (str): Primary replication fabric/location.
            protected_item_name (str): Protected item name in ASR.
            query_status (str): "success" or "error".
            duration_ms (int): Query duration in milliseconds.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_asr_replication_health",
        tool_parameters={"resource_group": resource_group, "vm_name": vm_name},
        correlation_id=vm_name,
        thread_id=thread_id,
    ):
        try:
            if ResourceGraphClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-resourcegraph not installed",
                    "vm_name": vm_name,
                    "asr_enabled": False,
                    "replication_health": "not_configured",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }
            if SiteRecoveryManagementClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-mgmt-recoveryservicessiterecovery not installed",
                    "vm_name": vm_name,
                    "asr_enabled": False,
                    "replication_health": "not_configured",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()

            # Step 1: Find Recovery Services vaults via ARG
            arg_client = ResourceGraphClient(credential)
            vault_query = QueryRequest(
                subscriptions=[subscription_id],
                query=(
                    "Resources "
                    "| where type == 'microsoft.recoveryservices/vaults' "
                    "| project name, resourceGroup, location"
                ),
                options=QueryRequestOptions(result_format="objectArray"),
            )
            vault_response = arg_client.resources(vault_query)
            vaults = list(vault_response.data or [])

            if not vaults:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "vm_name": vm_name,
                    "resource_group": resource_group,
                    "subscription_id": subscription_id,
                    "asr_enabled": False,
                    "vault_name": "",
                    "replication_health": "not_configured",
                    "failover_readiness": "",
                    "rpo_seconds": -1,
                    "primary_fabric": "",
                    "protected_item_name": "",
                    "query_status": "success",
                    "duration_ms": duration_ms,
                }

            # Step 2: Search each vault for a replication protected item for this VM
            vm_resource_id_lower = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
            ).lower()

            for vault in vaults:
                vault_name = vault.get("name", "")
                vault_rg = vault.get("resourceGroup", "")
                if not vault_name or not vault_rg:
                    continue
                try:
                    asr_client = SiteRecoveryManagementClient(
                        credential, subscription_id, vault_name, vault_rg
                    )
                    for item in asr_client.replication_protected_items.list():
                        props = getattr(item, "properties", None)
                        prov_info = getattr(props, "provider_specific_details", None)
                        fabric_obj_id = str(
                            getattr(prov_info, "fabric_object_id", "") or ""
                        ).lower()
                        if fabric_obj_id == vm_resource_id_lower or vm_name.lower() in fabric_obj_id:
                            replication_health = str(
                                getattr(props, "replication_health", "Unknown") or "Unknown"
                            )
                            failover_readiness = str(
                                getattr(props, "failover_readiness", "") or ""
                            )
                            rpo_seconds = -1
                            rpo_raw = getattr(props, "current_scenario", None)
                            if rpo_raw:
                                rpo_val = getattr(rpo_raw, "recovery_point_objective_in_seconds", None)
                                if rpo_val is not None:
                                    rpo_seconds = int(rpo_val)
                            primary_fabric = str(
                                getattr(props, "primary_fabric_friendly_name", "") or ""
                            )
                            protected_item_name = item.name or ""

                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            logger.info(
                                "query_asr_replication_health: found | vm=%s vault=%s health=%s duration_ms=%d",
                                vm_name, vault_name, replication_health, duration_ms,
                            )
                            return {
                                "vm_name": vm_name,
                                "resource_group": resource_group,
                                "subscription_id": subscription_id,
                                "asr_enabled": True,
                                "vault_name": vault_name,
                                "replication_health": replication_health,
                                "failover_readiness": failover_readiness,
                                "rpo_seconds": rpo_seconds,
                                "primary_fabric": primary_fabric,
                                "protected_item_name": protected_item_name,
                                "query_status": "success",
                                "duration_ms": duration_ms,
                            }
                except Exception:
                    # Swallow per-vault errors and continue to next vault
                    continue

            # No ASR item found across all vaults
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info("query_asr_replication_health: vm not protected | vm=%s", vm_name)
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "asr_enabled": False,
                "vault_name": "",
                "replication_health": "not_configured",
                "failover_readiness": "",
                "rpo_seconds": -1,
                "primary_fabric": "",
                "protected_item_name": "",
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_asr_replication_health error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "asr_enabled": False,
                "replication_health": "not_configured",
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```

---

## Verification

```bash
# Confirm 5 new tools present (28 original + 5 = 33 minimum)
grep -c "@ai_function" agents/compute/tools.py

# Confirm all 5 tool function names exist
grep "^def query_defender_tvm_cve_count" agents/compute/tools.py
grep "^def query_jit_access_status" agents/compute/tools.py
grep "^def query_effective_nsg_rules" agents/compute/tools.py
grep "^def query_backup_rpo" agents/compute/tools.py
grep "^def query_asr_replication_health" agents/compute/tools.py

# Confirm required return fields exist
grep "vm_risk_score" agents/compute/tools.py
grep '"jit_enabled"' agents/compute/tools.py
grep '"effective_rules"' agents/compute/tools.py
grep '"backup_enabled"' agents/compute/tools.py
grep '"asr_enabled"' agents/compute/tools.py

# Confirm requirements.txt has new packages
grep "azure-mgmt-security" agents/compute/requirements.txt
grep "azure-mgmt-network" agents/compute/requirements.txt
grep "azure-mgmt-recoveryservicesbackup" agents/compute/requirements.txt
grep "azure-mgmt-recoveryservicessiterecovery" agents/compute/requirements.txt
```
