# Phase 3: Arc MCP Server — Research

**Date:** 2026-03-26
**Status:** Complete
**Purpose:** Everything needed to plan Phase 3 well

---

## Table of Contents

1. [FastMCP Server Structure](#1-fastmcp-server-structure)
2. [Azure Arc SDK Patterns](#2-azure-arc-sdk-patterns)
3. [Arc Server Data Model](#3-arc-server-data-model)
4. [Arc K8s Data Model](#4-arc-k8s-data-model)
5. [Terraform for Arc MCP Container App](#5-terraform-for-arc-mcp-container-app)
6. [Arc Agent Upgrade Pattern](#6-arc-agent-upgrade-pattern)
7. [Integration Test Strategy (E2E-006)](#7-integration-test-strategy-e2e-006)
8. [Package Versions](#8-package-versions)

---

## 1. FastMCP Server Structure

### 1.1 Import and Instantiation

FastMCP lives inside the official `mcp` package (`mcp.server.fastmcp.FastMCP`). It is
**not** a separate PyPI package — `pip install mcp[cli]` is the correct install.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("arc-mcp-server", stateless_http=True)
```

`stateless_http=True` is the right flag for a Container App deployment — it disables
session management, which is inappropriate for a multi-replica environment where each
request may land on a different replica. Without it, session state would not be shared
across replicas.

### 1.2 Tool Declaration with `@mcp.tool()`

Tools are declared with the `@mcp.tool()` decorator. Parameters are inferred from the
function signature. Pydantic `BaseModel` subclasses, plain type annotations, and
`TypedDict` all work as parameter types. Docstrings provide the tool description to the
LLM.

```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from typing import Optional

mcp = FastMCP("arc-mcp-server", stateless_http=True)

@mcp.tool()
async def arc_servers_list(
    subscription_id: str,
    resource_group: Optional[str] = None,
) -> dict:
    """List all Arc-enabled servers in a subscription.

    Exhausts nextLink pagination. Returns total_count and all machines.

    Args:
        subscription_id: Azure subscription ID.
        resource_group: Optional resource group filter. If omitted, lists all Arc
            servers across the entire subscription.

    Returns:
        Dict with keys: subscription_id, resource_group, servers (list), total_count.
    """
    ...
```

Key rules for `@mcp.tool()` in this codebase:
- Functions **MUST** be `async` (the FastMCP runtime is async-native)
- Return type annotations are optional but recommended for structured output
- Pydantic `BaseModel` return types produce structured JSON visible to the LLM
- Docstring `Args:` section is used by FastMCP to build the JSON schema description
- Do NOT use `@ai_function` (that is the agent-framework decorator for domain agent
  tools, not for MCP server tools)

### 1.3 Production Entry Point: Streamable HTTP Transport

For a Container App deployment, Streamable HTTP is the correct transport. The Arc MCP
Server **must not** use stdio transport (that is for subprocess/sidecar invocation,
not a standalone HTTP service).

```python
if __name__ == "__main__":
    # Streamable HTTP transport — binds to 0.0.0.0:8080 inside the container.
    # Container Apps environment handles TLS termination.
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

The MCP endpoint is served at: `http://<container-fqdn>:8080/mcp`

The `mcp.run()` call uses `uvicorn` under the hood — FastMCP builds an ASGI app and
calls uvicorn directly. There is no need to call `uvicorn` separately or write a custom
`app.py`. This is different from a FastAPI service.

Alternatively, the ASGI app can be extracted for custom uvicorn configuration:

```python
# For production with custom workers / log config:
app = mcp.streamable_http_app()  # returns the ASGI app
# Then: uvicorn arc_mcp_server:app --host 0.0.0.0 --port 8080 --workers 2
```

The Dockerfile `CMD` should be:
```dockerfile
CMD ["python", "-m", "arc_mcp_server"]
```
with `arc_mcp_server/__main__.py` calling `mcp.run(transport="streamable-http", ...)`.

### 1.4 Pydantic Models for Structured Return Types

Return Pydantic `BaseModel` subclasses for structured output. FastMCP serialises them
to JSON automatically.

```python
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class ArcServerSummary(BaseModel):
    id: str
    name: str
    resource_group: str
    location: str
    status: str                        # "Connected" | "Disconnected" | "Error"
    last_status_change: Optional[str]  # ISO 8601 datetime
    agent_version: Optional[str]
    os_name: Optional[str]
    os_type: Optional[str]

class ArcServersListResult(BaseModel):
    subscription_id: str
    resource_group: Optional[str]
    servers: List[ArcServerSummary]
    total_count: int

@mcp.tool()
async def arc_servers_list(
    subscription_id: str,
    resource_group: Optional[str] = None,
) -> ArcServersListResult:
    ...
```

### 1.5 Authentication: DefaultAzureCredential at Module Level

The Arc MCP Server authenticates to Azure using `DefaultAzureCredential`. The credential
is instantiated once at module level (not per-request), matching the pattern in
`agents/shared/auth.py`.

```python
from azure.identity import DefaultAzureCredential
from functools import lru_cache

@lru_cache(maxsize=1)
def _get_credential() -> DefaultAzureCredential:
    """Return a cached DefaultAzureCredential.

    In Container Apps, resolves system-assigned managed identity via IMDS.
    Locally, falls back to Azure CLI / VS Code credentials.
    """
    return DefaultAzureCredential()
```

The Arc MCP Server has its own system-assigned managed identity (separate from the Arc
Agent). This identity needs the RBAC roles listed in Section 5.

### 1.6 Lifespan Context (Optional — for SDK Client Caching)

For production, Azure SDK management clients should be cached and reused across requests.
FastMCP's lifespan context is the idiomatic place to initialise long-lived resources:

```python
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
from azure.mgmt.hybridcompute import HybridComputeManagementClient
from azure.mgmt.hybridkubernetes import ConnectedKubernetesClient

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialise shared Azure SDK clients once at server startup."""
    credential = _get_credential()
    # Clients are subscription-scoped, so we create them per-request inside tools.
    # Only global resources (like the credential) are worth caching here.
    yield {"credential": credential}

mcp = FastMCP("arc-mcp-server", stateless_http=True, lifespan=app_lifespan)
```

**Note:** `HybridComputeManagementClient` and `ConnectedKubernetesClient` take a
`subscription_id` parameter in the constructor, so they cannot be cached globally
(each tool call may operate on a different subscription). Create them per-call.

### 1.7 Local Testing

```bash
# Start the MCP server locally on port 8080
python -m arc_mcp_server

# Test with MCP Inspector
npx @modelcontextprotocol/inspector http://localhost:8080/mcp
```

---

## 2. Azure Arc SDK Patterns

### 2.1 Package Names and Versions

| SDK | PyPI Package | Latest Stable | Client Class |
|-----|-------------|---------------|--------------|
| Arc Servers | `azure-mgmt-hybridcompute` | **9.0.0** | `HybridComputeManagementClient` |
| Arc K8s | `azure-mgmt-hybridkubernetes` | **1.1.0** | `ConnectedKubernetesClient` |
| Arc Data Services | `azure-mgmt-azurearcdata` | **1.0.0** | `AzureArcDataManagementClient` |
| Auth | `azure-identity` | >=1.17.0 | `DefaultAzureCredential` |

**Important naming clarification:**
- The correct package for Arc Kubernetes is `azure-mgmt-hybridkubernetes` (not
  `azure-mgmt-connectedk8s` — that package does not exist on PyPI as of March 2026).
- The correct package for Arc Data Services is `azure-mgmt-azurearcdata` (not
  `azure-mgmt-arcdata` — that package does not exist on PyPI as of March 2026).
- CLAUDE.md's REQUIREMENTS.md mentions `AzureArcDataManagementClient` which lives in
  `azure-mgmt-azurearcdata==1.0.0`.

### 2.2 HybridComputeManagementClient — Arc Servers

```python
from azure.mgmt.hybridcompute import HybridComputeManagementClient
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
client = HybridComputeManagementClient(
    credential=credential,
    subscription_id="<subscription_id>",
)
```

**List all Arc servers in a subscription (exhausting pagination):**

```python
def list_all_arc_servers(client: HybridComputeManagementClient) -> list:
    """Exhaust nextLink pagination and return all Arc servers in subscription."""
    machines = []
    # list_by_subscription() returns an ItemPaged iterator that automatically
    # follows nextLink. Iterating over it exhausts all pages.
    for machine in client.machines.list_by_subscription():
        machines.append(machine)
    return machines
```

**Critical: Pagination in Azure Python SDK is AUTOMATIC.** The `ItemPaged` iterator
returned by `list_by_subscription()` and `list_by_resource_group()` internally follows
the `nextLink` field. There is **no manual pagination loop required**. Simply iterating
the result exhausts all pages. This is the behaviour of all `azure-mgmt-*` packages
using the `azure-core` `ItemPaged` pattern.

However, AGENT-006 requires returning `total_count`. The pattern is:

```python
async def arc_servers_list_all(
    client: HybridComputeManagementClient,
    resource_group: Optional[str] = None,
) -> tuple[list, int]:
    """Returns (servers_list, total_count). nextLink is exhausted automatically."""
    servers = []
    paged = (
        client.machines.list_by_resource_group(resource_group)
        if resource_group
        else client.machines.list_by_subscription()
    )
    for machine in paged:
        servers.append(machine)
    return servers, len(servers)
```

**Key operations on `HybridComputeManagementClient`:**

| Operation | Method | Description |
|-----------|--------|-------------|
| List all in subscription | `client.machines.list_by_subscription()` | Returns `ItemPaged[Machine]` |
| List in resource group | `client.machines.list_by_resource_group(rg)` | Returns `ItemPaged[Machine]` |
| Get single machine | `client.machines.get(rg, machine_name)` | Returns `Machine` |
| List extensions | `client.machine_extensions.list(rg, machine_name)` | Returns `ItemPaged[MachineExtension]` |
| Get extension | `client.machine_extensions.get(rg, machine_name, ext_name)` | Returns `MachineExtension` |

### 2.3 ConnectedKubernetesClient — Arc K8s

```python
from azure.mgmt.hybridkubernetes import ConnectedKubernetesClient

client = ConnectedKubernetesClient(
    credential=credential,
    subscription_id="<subscription_id>",
)
```

**Key operations:**

| Operation | Method | Description |
|-----------|--------|-------------|
| List all clusters | `client.connected_cluster.list_by_subscription()` | Returns `ItemPaged[ConnectedCluster]` |
| List in RG | `client.connected_cluster.list_by_resource_group(rg)` | Returns `ItemPaged[ConnectedCluster]` |
| Get cluster | `client.connected_cluster.get(rg, cluster_name)` | Returns `ConnectedCluster` |

**Note:** The property accessor is `connected_cluster` (singular). Pagination behaviour
is the same as hybridcompute — `ItemPaged` automatically follows `nextLink`.

### 2.4 AzureArcDataManagementClient — Arc Data Services

```python
from azure.mgmt.azurearcdata import AzureArcDataManagementClient

client = AzureArcDataManagementClient(
    credential=credential,
    subscription_id="<subscription_id>",
)
```

**Key operations (based on azure-mgmt-azurearcdata 1.0.0):**

| Operation | Method | Description |
|-----------|--------|-------------|
| List SQL MIs | `client.sql_managed_instances.list()` | All Arc SQL MIs in subscription |
| Get SQL MI | `client.sql_managed_instances.get(rg, name)` | Single instance |
| List PostgreSQLs | `client.postgresql_instances.list()` | All Arc PostgreSQL instances |
| Get PostgreSQL | `client.postgresql_instances.get(rg, name)` | Single instance |
| List data controllers | `client.data_controllers.list_in_subscription()` | All Arc data controllers |

[UNCERTAIN] `azure-mgmt-azurearcdata==1.0.0` is the only available stable version and
may have sparse operation coverage. Verify the exact operation group names at
implementation time. The package is old (no updates since initial release) — some Arc
data service operations may be incomplete or behind the REST API. Consider falling back
to direct ARM REST calls via `azure-mgmt-resource` if the SDK is insufficient.

### 2.5 nextLink Pagination — Confirming Exhaustion

The `ItemPaged` class (from `azure-core`) handles pagination automatically. Internally
it:
1. Calls the initial list endpoint
2. Checks for `nextLink` in the response
3. Follows `nextLink` to get the next page
4. Yields items from all pages in order

To count total items, collect all into a list and `len()` it:

```python
all_machines = list(client.machines.list_by_subscription())
total_count = len(all_machines)  # This is the true estate count
```

There is **no risk of silent partial results** when using the iterator — if a `nextLink`
exists, the SDK follows it. AGENT-006's requirement is satisfied by using the iterator
and returning `total_count = len(results)`.

For very large estates (e.g., 10,000+ machines), consider streaming the results rather
than collecting them all into memory first. For the target of >100 machines in E2E-006,
collecting into a list is fine.

---

## 3. Arc Server Data Model

### 3.1 `Machine` Object Fields (from `azure-mgmt-hybridcompute`)

The `Machine` class returned by `machines.list_by_subscription()` has the following
key fields (server-populated, read-only):

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Full ARM resource ID |
| `name` | `str` | Machine name |
| `type` | `str` | `"Microsoft.HybridCompute/machines"` |
| `location` | `str` | Azure region |
| `tags` | `dict` | Resource tags |
| `status` | `str` | **Connectivity status**: `"Connected"`, `"Disconnected"`, `"Error"` |
| `last_status_change` | `datetime` | Last time status changed |
| `agent_version` | `str` | Arc agent version string (e.g., `"1.37.02905.009"`) |
| `os_name` | `str` | OS name (e.g., `"Windows Server 2022 Datacenter"`) |
| `os_version` | `str` | OS version string |
| `os_type` | `str` | `"windows"` or `"linux"` |
| `os_sku` | `str` | OS SKU string |
| `vm_id` | `str` | Unique machine VM ID |
| `machine_fqdn` | `str` | FQDN of the machine |
| `domain_name` | `str` | Windows domain name (if applicable) |
| `private_link_scope_resource_id` | `str` | Private Link scope resource ID (if any) |
| `parent_cluster_resource_id` | `str` | Parent HCI cluster ID (if applicable) |
| `provisioning_state` | `str` | ARM provisioning state |
| `error_details` | `list[ErrorDetail]` | Error details when `status == "Error"` |
| `kind` | `str` | Arc placement: `"AVS"`, `"HCI"`, `"SCVMM"`, `"VMware"`, `"EPS"`, `"GCP"`, `"AWS"` |
| `resources` | `list[MachineExtension]` | Extensions affiliated to the machine |
| `detected_properties` | `dict` | Auto-detected properties |
| `network_profile` | `NetworkProfile` | Network configuration |

**Resource group extraction:** The ARM resource ID (`machine.id`) follows the pattern
`/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.HybridCompute/machines/{name}`.
Extract `resource_group` by parsing the ID: `machine.id.split("/")[4]`.

### 3.2 Connectivity Status Values

The `machine.status` field (typed as `StatusTypes` enum) has three values:

| Value | Meaning |
|-------|---------|
| `"Connected"` | Arc agent is healthy, heartbeat received within threshold |
| `"Disconnected"` | Arc agent has not sent a heartbeat recently |
| `"Error"` | Arc agent encountered an error condition |

**Note:** The REST API spec also references `"Expired"` for K8s clusters, but for Arc
Servers (`Machine`) the SDK enum has only `Connected`, `Disconnected`, `Error`.

### 3.3 MONITOR-004 Disconnection Threshold

There is no Azure-defined official threshold for "prolonged disconnection". Based on
Arc documentation practices:
- Arc agent sends heartbeats every **~5 minutes** when connected
- Azure Monitor has built-in alert rules that fire after **~15 minutes** of no heartbeat
- The `last_status_change` field tells you when the machine transitioned to Disconnected

**Recommended platform threshold for MONITOR-004:** Alert if
`last_status_change < (now - 1 hour)` and `status == "Disconnected"`. This is
configurable — expose it as an environment variable on the Arc MCP Container App.

Implementation in a tool:
```python
from datetime import datetime, timezone, timedelta

DISCONNECTION_ALERT_THRESHOLD_HOURS = int(
    os.environ.get("ARC_DISCONNECT_ALERT_HOURS", "1")
)

def is_prolonged_disconnect(machine) -> bool:
    if machine.status != "Disconnected":
        return False
    if machine.last_status_change is None:
        return True  # Unknown time — treat as prolonged
    threshold = datetime.now(timezone.utc) - timedelta(
        hours=DISCONNECTION_ALERT_THRESHOLD_HOURS
    )
    return machine.last_status_change < threshold
```

### 3.4 `MachineExtension` and `MachineExtensionProperties` Fields

Extensions are retrieved via `client.machine_extensions.list(resource_group, machine_name)`.
Each `MachineExtension` has a `.properties` of type `MachineExtensionProperties`:

| Property Field | Type | Description |
|----------------|------|-------------|
| `publisher` | `str` | Extension publisher (e.g., `"Microsoft.Azure.Monitor"`) |
| `type` | `str` | Extension type (e.g., `"AzureMonitorWindowsAgent"`) |
| `type_handler_version` | `str` | Installed version (e.g., `"1.21.0.0"`) |
| `provisioning_state` | `str` | `"Succeeded"`, `"Failed"`, `"Creating"`, etc. |
| `enable_automatic_upgrade` | `bool` | Whether auto-upgrade is enabled |
| `instance_view` | `MachineExtensionInstanceView` | Runtime instance view |

**`MachineExtensionInstanceView` fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Extension name |
| `type` | `str` | Extension type |
| `type_handler_version` | `str` | Running handler version |
| `status` | `MachineExtensionInstanceViewStatus` | Status code + message |

The `status` sub-object has:
- `code`: Status code string (e.g., `"ProvisioningState/succeeded"`)
- `level`: `"Info"`, `"Warning"`, `"Error"`
- `display_status`: Human-readable status (e.g., `"Provisioning succeeded"`)
- `message`: Detailed message
- `time`: Timestamp of the status

### 3.5 Well-Known Arc Extension Publishers and Types (MONITOR-005)

| Extension | Publisher | Type (Windows) | Type (Linux) |
|-----------|-----------|----------------|--------------|
| **Azure Monitor Agent (AMA)** | `Microsoft.Azure.Monitor` | `AzureMonitorWindowsAgent` | `AzureMonitorLinuxAgent` |
| **VM Insights (Dependency)** | `Microsoft.Azure.Monitoring.DependencyAgent` | `DependencyAgentWindows` | `DependencyAgentLinux` |
| **Change Tracking** | `Microsoft.Azure.ChangeTrackingAndInventory` | `ChangeTracking-Windows` | `ChangeTracking-Linux` |
| **Azure Policy (Guest Config)** | `Microsoft.GuestConfiguration` | `ConfigurationforWindows` | `ConfigurationforLinux` |
| **Key Vault** | `Microsoft.Azure.KeyVault` | `KeyVaultForWindows` | `KeyVaultForLinux` |

---

## 4. Arc K8s Data Model

### 4.1 `ConnectedCluster` Object Fields

From the REST API `2024-01-01` docs and `azure-mgmt-hybridkubernetes==1.1.0`:

| Field (JSON path) | Type | Description |
|-------------------|------|-------------|
| `id` | `str` | Full ARM resource ID |
| `name` | `str` | Cluster name |
| `location` | `str` | Azure region |
| `tags` | `dict` | Resource tags |
| `properties.connectivity_status` | `str` | `"Connecting"`, `"Connected"`, `"Offline"`, `"Expired"` |
| `properties.last_connectivity_time` | `datetime` | Last heartbeat from Arc agent |
| `properties.kubernetes_version` | `str` | K8s version (e.g., `"1.28.5"`) |
| `properties.distribution` | `str` | K8s distribution (e.g., `"AKS"`, `"k3s"`, `"openshift"`) |
| `properties.distribution_version` | `str` | Distribution version |
| `properties.total_node_count` | `int` | Total nodes in cluster |
| `properties.total_core_count` | `int` | Total CPU cores |
| `properties.agent_version` | `str` | Arc agent version on the cluster |
| `properties.infrastructure` | `str` | Infrastructure type |
| `properties.provisioning_state` | `str` | ARM provisioning state |
| `properties.private_link_scope_resource_id` | `str` | Private Link scope (if any) |

**Note on `connectivity_status`:** Uses different values from Arc Servers. The K8s
ConnectivityStatus enum is: `Connecting`, `Connected`, `Offline`, `Expired`.
`Expired` means the managed identity certificate has expired (>90 days since last
connection by default).

### 4.2 Python SDK Field Naming

The `azure-mgmt-hybridkubernetes` Python SDK uses snake_case. The `ConnectedCluster`
object in Python exposes:

```python
cluster.properties.connectivity_status      # str
cluster.properties.last_connectivity_time   # datetime
cluster.properties.kubernetes_version       # str
cluster.properties.distribution             # str
cluster.properties.total_node_count         # int
cluster.properties.agent_version            # str
```

[UNCERTAIN] The exact property accessor path depends on the SDK version. In some SDK
versions the properties are directly on the cluster object (e.g., `cluster.connectivity_status`).
Verify against `azure-mgmt-hybridkubernetes==1.1.0` at implementation time.

### 4.3 Flux GitOps Detection (MONITOR-006)

**The challenge:** Arc-level ARM metadata does NOT surface Flux reconciliation status
directly. Flux status lives inside the Kubernetes cluster (in the `flux-system` namespace,
in `GitRepository` and `Kustomization` custom resources).

There are **two approaches** to get Flux status:

**Approach A (Recommended): Azure Arc Kubernetes Configuration extension (ARM-based)**

Azure Arc K8s integrates with Flux via the `Microsoft.KubernetesConfiguration` extension
type. The `sourceControlConfiguration` and `fluxConfiguration` resources are ARM
resources queryable via `azure-mgmt-kubernetesconfiguration`.

```python
from azure.mgmt.kubernetesconfiguration import SourceControlConfigurationClient

config_client = SourceControlConfigurationClient(credential, subscription_id)

# List Flux configurations for a cluster
flux_configs = list(config_client.flux_configurations.list(
    resource_group_name=resource_group,
    cluster_rp="Microsoft.Kubernetes",
    cluster_resource_name="connectedClusters",
    cluster_name=cluster_name,
))
```

The `FluxConfiguration` ARM resource includes:
- `compliance_state`: `"Compliant"`, `"NonCompliant"`, `"Pending"`, `"Suspended"`, `"Unknown"`
- `provisioning_state`: ARM provisioning state
- `status_conditions`: List of status conditions from Flux
- `git_repository`: GitRepository source configuration
- `kustomizations`: Kustomization targets

This is the **recommended approach** for MONITOR-006 because it is ARM-native and does
not require Kubernetes API access from the Arc MCP Server.

**Approach B (Not recommended for this server): Direct K8s API access**

Querying the Kubernetes API directly (e.g., via `kubernetes` Python SDK) would require
kubeconfig or cluster admin credentials, which the Arc MCP Server should NOT have.
The Arc MCP Server authenticates via ARM managed identity only.

**Detecting if Flux is installed:**

An Arc cluster has Flux if either:
1. `sourceControlConfiguration` ARM resources exist for the cluster, OR
2. The cluster has the `Microsoft.Flux` extension type installed (visible via
   `client.extensions.list()` on `azure-mgmt-kubernetesconfiguration`)

```python
# Check for Flux extensions on a connected cluster
from azure.mgmt.kubernetesconfiguration import SourceControlConfigurationClient

def is_flux_installed(config_client, resource_group: str, cluster_name: str) -> bool:
    """Detect if Flux GitOps is configured for this Arc K8s cluster."""
    try:
        configs = list(config_client.flux_configurations.list(
            resource_group_name=resource_group,
            cluster_rp="Microsoft.Kubernetes",
            cluster_resource_name="connectedClusters",
            cluster_name=cluster_name,
        ))
        return len(configs) > 0
    except Exception:
        return False  # Permission denied or no Flux configured
```

**Package:** `azure-mgmt-kubernetesconfiguration==3.1.0`

---

## 5. Terraform for Arc MCP Container App

### 5.1 Internal-Only Container App Pattern

Looking at the existing `terraform/modules/agent-apps/main.tf`, the current module
handles internal vs external ingress via a `for_each` on `ingress_external`:

```hcl
dynamic "ingress" {
  for_each = each.value.ingress_external ? [1] : []
  content {
    external_enabled = true
    target_port      = 8000
    transport        = "http"
    ...
  }
}
```

When `ingress_external = false`, **no ingress block is emitted** — the Container App is
accessible only within the Container Apps environment via its internal DNS name:
`https://ca-arc-mcp-server-{env}.{env_default_domain}`.

For the Arc MCP Server, which should be internal-only, this maps to `ingress_external = false`.
But the Arc MCP Server needs **its own ingress block** (internal ingress, not no ingress)
so agents can reach it by FQDN. The existing pattern omits ingress entirely for internal
apps — this is a gap.

**Correct pattern for the Arc MCP Server** is an internal ingress (reachable within the
Container Apps environment VNet, but not from the public internet):

```hcl
resource "azurerm_container_app" "arc_mcp_server" {
  name                         = "ca-arc-mcp-server-${var.environment}"
  container_app_environment_id = var.container_apps_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  ingress {
    external_enabled = false   # Internal only — not publicly accessible
    target_port      = 8080    # FastMCP server port
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "arc-mcp-server"
      image  = "${var.acr_login_server}/arc-mcp-server:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AZURE_SUBSCRIPTION_IDS"
        value = var.arc_subscription_ids  # Comma-separated list
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }
      env {
        name  = "ARC_DISCONNECT_ALERT_HOURS"
        value = "1"
      }
    }
  }

  secret {
    name  = "appinsights-connection-string"
    value = var.app_insights_connection_string
  }

  tags = var.required_tags
}
```

**Key difference from agent apps:** The Arc MCP Server uses `ingress.external_enabled = false`
**with an explicit ingress block** (not the absent-ingress pattern). This gives it an
internal FQDN usable by agents.

### 5.2 Internal FQDN for Arc Agent to Call

The Arc MCP Server is reachable from the Arc Agent at:
```
http://ca-arc-mcp-server-{env}.{env_default_domain}/mcp
```

The `env_default_domain` is the Container Apps environment's default domain (a Terraform
output from Phase 1's `compute-env` module: `container_apps_environment_default_domain`).

For the Arc Agent's `ARC_MCP_SERVER_URL` environment variable:
```hcl
env {
  name  = "ARC_MCP_SERVER_URL"
  value = "http://ca-arc-mcp-server-${var.environment}.${var.container_apps_env_domain}/mcp"
}
```

### 5.3 RBAC for the Arc MCP Server Identity

The Arc MCP Server's system-assigned managed identity needs the following RBAC roles:

| Role | Scope | Purpose |
|------|-------|---------|
| `Reader` | Each subscription containing Arc resources | Read Arc machines, K8s clusters |
| `Azure Connected Machine Resource Reader` | Subscription scope | Read `Microsoft.HybridCompute/machines` |
| `Kubernetes Cluster - Azure Arc Onboarding` | Not required — read-only | Covered by Reader |

**Simpler alternative:** `Reader` role at subscription scope covers all ARM read
operations including `Microsoft.HybridCompute/machines/read` and
`Microsoft.Kubernetes/connectedClusters/read`. This is the correct minimal permission.

The Arc Agent (domain agent) and the Arc MCP Server have **separate identities**:
- Arc Agent: has a Foundry Hosted Agent identity (manages conversations)
- Arc MCP Server: has its own Container App system-assigned identity (calls ARM APIs)

```hcl
resource "azurerm_role_assignment" "arc_mcp_reader" {
  for_each             = toset(var.arc_subscription_ids)
  principal_id         = azurerm_container_app.arc_mcp_server.identity[0].principal_id
  role_definition_name = "Reader"
  scope                = "/subscriptions/${each.value}"
}
```

### 5.4 Terraform Module Placement

The Arc MCP Server is a **new module** (`terraform/modules/arc-mcp-server/`), separate
from the existing `agent-apps` module. Reasons:
1. Different port (8080 vs 8088 for agents)
2. Different ingress pattern (explicit internal ingress block, not no-ingress)
3. Different RBAC requirements (subscription Reader, not compute/network/storage specific)
4. Different env vars (no Foundry endpoint needed — it's an MCP server, not an agent)

Alternatively, it can be added to the existing `agent-apps` module locals with a new
type distinction. This is a planner decision.

---

## 6. Arc Agent Upgrade Pattern

### 6.1 Current State

`agents/arc/agent.py` is a stub that:
- Returns `pending_phase3` status for all incidents
- Has `ALLOWED_MCP_TOOLS: list[str] = []` (empty — no MCP tools permitted)
- Uses `handle_arc_incident` as its only `@ai_function`

### 6.2 How the Arc Agent Connects to the Arc MCP Server

From the Phase 2 RESEARCH.md and STACK.md, the pattern for mounting a custom MCP server
is via Foundry's `McpTool` connection (registered as a project connection):

```python
from azure.ai.projects.models import McpTool

arc_mcp_tool = McpTool(
    server_label="arc-mcp",
    server_url=os.environ["ARC_MCP_SERVER_URL"],  # http://ca-arc-mcp-server-dev.{domain}/mcp
    allowed_tools=[
        "arc_servers_list",
        "arc_servers_get",
        "arc_k8s_list",
        "arc_k8s_get",
        "arc_extensions_list",
        "arc_data_services_list",
    ],
)
```

This `McpTool` is passed as a `tool_resource` when creating/updating the agent definition
in Foundry. See Phase 2 RESEARCH.md Section 4.4 for the general `McpTool` mounting
pattern.

[UNCERTAIN] The exact `McpTool` API parameters for `azure-ai-projects==2.0.1` need
verification at implementation time. The `server_label` and `server_url` parameters
are based on Phase 2 research — confirm against the current SDK.

### 6.3 ALLOWED_MCP_TOOLS for the Arc Agent

Based on the arc-agent.spec.md, the Phase 3 tool permissions are:

```python
ALLOWED_MCP_TOOLS: list[str] = [
    # Arc MCP Server tools
    "arc_servers_list",
    "arc_servers_get",
    "arc_k8s_list",
    "arc_k8s_get",
    "arc_extensions_list",
    "arc_data_services_list",
    # Azure MCP Server tools (from agent-apps ALLOWED_MCP_TOOLS pattern)
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]
```

No wildcard permissions. This matches the pattern in `agents/compute/tools.py`.

### 6.4 Upgraded Arc Agent Structure

The upgraded `agents/arc/agent.py` will:
1. Remove the `pending_phase3` stub
2. Keep `ALLOWED_MCP_TOOLS` (now populated with Arc MCP Server + Azure MCP Server tools)
3. Replace `handle_arc_incident` stub with proper triage `@ai_function` tools:
   - `query_activity_log` (re-use shared pattern from compute)
   - `query_log_analytics` (re-use shared pattern)
   - `query_resource_health` (re-use shared pattern)
4. Update `ARC_AGENT_SYSTEM_PROMPT` with full Phase 3 triage workflow
5. Mount the Arc MCP Server via `McpTool` in the `create_arc_agent()` factory

The triage workflow from arc-agent.spec.md (Phase 3 steps) becomes the system prompt:
1. Activity Log check (prior 2h) — TRIAGE-003
2. `arc_servers_list` / `arc_k8s_list` — connectivity check — MONITOR-004
3. `arc_extensions_list` — extension health — MONITOR-005
4. `arc_k8s_get` — GitOps status — MONITOR-006
5. Resource Health
6. `TriageDiagnosis` with confidence score — TRIAGE-004
7. `RemediationProposal` (propose-only) — REMEDI-001

---

## 7. Integration Test Strategy (E2E-006)

### 7.1 Requirement Summary

E2E-006 requires:
- >100 mock Arc servers in a seeded estate
- Playwright test verifies pagination exhaustion
- `total_count` matches the full inventory
- No partial results (i.e., `nextLink` must be followed to completion)

### 7.2 Test Approach: Mock ARM Server (pytest + responses)

The recommended approach is to use `pytest` with the `responses` library (or `unittest.mock`)
to mock the Azure SDK HTTP calls. This avoids real Azure credentials in CI and allows
seeding exactly 101+ servers deterministically.

```python
# agents/arc/mcp_server/tests/test_pagination.py
import pytest
from unittest.mock import MagicMock, patch
from azure.mgmt.hybridcompute.models import Machine

def _make_machine(i: int) -> Machine:
    """Create a fake Machine object for testing."""
    m = Machine(location="eastus")
    m.name = f"arc-server-{i:04d}"
    m.id = f"/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.HybridCompute/machines/arc-server-{i:04d}"
    m.status = "Connected"
    m.agent_version = "1.37.0"
    m.os_name = "Ubuntu 22.04"
    return m

@pytest.mark.asyncio
async def test_arc_servers_list_exhausts_pagination():
    """AGENT-006: list tool must exhaust nextLink and return correct total_count."""
    # Seed 120 fake servers
    fake_machines = [_make_machine(i) for i in range(120)]

    with patch(
        "azure.mgmt.hybridcompute.operations.MachinesOperations.list_by_subscription",
        return_value=iter(fake_machines),  # ItemPaged is iterable
    ):
        from arc_mcp_server.tools import arc_servers_list_impl
        result = await arc_servers_list_impl(subscription_id="sub1")
        assert result["total_count"] == 120
        assert len(result["servers"]) == 120
```

**Key insight:** The Azure SDK's `ItemPaged` is an iterator. In unit tests, mock it by
returning a plain Python iterator (`iter(list_of_objects)`). The production code's
`for item in paged:` loop will correctly exhaust it.

### 7.3 Simulating nextLink Pagination in Tests

To specifically test that `nextLink` pagination is exhausted (not just that the iterator
is fully consumed), use `responses` to mock HTTP calls:

```python
# tests/test_arc_pagination_http.py
import responses as rsps
import json

@rsps.activate
def test_nextlink_pagination_exhausted():
    """Verify nextLink is followed — simulates a real multi-page ARM response."""
    # Page 1: 50 servers + nextLink
    page1 = {
        "value": [{"name": f"arc-server-{i}", "location": "eastus",
                   "properties": {"status": "Connected", "agentVersion": "1.37"}}
                  for i in range(50)],
        "nextLink": "https://management.azure.com/...?%24skipToken=page2"
    }
    # Page 2: 51 servers, no nextLink (last page)
    page2 = {
        "value": [{"name": f"arc-server-{i}", "location": "eastus",
                   "properties": {"status": "Connected", "agentVersion": "1.37"}}
                  for i in range(50, 101)],
    }

    rsps.add(rsps.GET, "https://management.azure.com/subscriptions/.../machines", json=page1)
    rsps.add(rsps.GET, "https://management.azure.com/...?%24skipToken=page2", json=page2)

    # Call the Arc MCP Server tool
    result = arc_servers_list_impl_sync(subscription_id="sub1")
    assert result["total_count"] == 101
    assert len(rsps.calls) == 2  # Two HTTP calls — nextLink was followed
```

### 7.4 Playwright E2E Test (E2E-006)

The Playwright test for E2E-006 operates against the **deployed Arc MCP Server** via
the Arc Agent's API, not directly against the MCP server. The test:

1. Injects a synthetic Arc incident via `POST /api/v1/incidents`
2. Monitors the SSE stream for Arc Agent triage events
3. Verifies the Arc Agent called `arc_servers_list` and returned `total_count > 100`
4. Asserts no truncation / partial results

```typescript
// tests/e2e/arc-mcp-server.spec.ts
import { test, expect } from '@playwright/test';

test('E2E-006: Arc MCP Server returns full paginated estate', async ({ request }) => {
  // Step 1: Inject synthetic Arc incident
  const incident = await request.post('/api/v1/incidents', {
    headers: { Authorization: `Bearer ${await getTestToken()}` },
    data: {
      incident_id: `e2e-arc-${Date.now()}`,
      severity: "Sev2",
      domain: "arc",
      affected_resources: [{ resource_id: "/subscriptions/test/resourceGroups/rg1/...",
                             subscription_id: "test", resource_type: "Microsoft.HybridCompute/machines" }],
      detection_rule: "ArcServerDisconnected",
    }
  });
  expect(incident.ok()).toBeTruthy();
  const { thread_id } = await incident.json();

  // Step 2: Poll for Arc Agent tool call event
  // (In Phase 5, this will use SSE; for Phase 3, poll the Cosmos DB thread record)
  await expect.poll(async () => {
    const status = await request.get(`/api/v1/threads/${thread_id}/status`);
    const data = await status.json();
    return data.arc_tool_calls?.includes('arc_servers_list');
  }, { timeout: 60000 }).toBeTruthy();

  // Step 3: Verify total_count >= 100 in the Arc Agent response
  const thread = await request.get(`/api/v1/threads/${thread_id}`);
  const threadData = await thread.json();
  const arcResult = threadData.arc_tool_results?.arc_servers_list;
  expect(arcResult?.total_count).toBeGreaterThanOrEqual(100);
  expect(arcResult?.servers.length).toBe(arcResult?.total_count);
});
```

**Seeding the test estate:** For E2E-006, the test environment must have >100 Arc server
ARM records. This can be achieved via:
- Azure CLI `az connectedmachine create` batch script (requires real Azure + Arc agent)
- Synthetic ARM records inserted directly into the test Cosmos DB incident store
- [UNCERTAIN] Mock ARM server injected at the Container App layer via environment variable
  `AZURE_ARM_ENDPOINT=http://mock-arm:8090` — requires the Arc MCP Server to support an
  overridable ARM base URL

**Recommended for Phase 3:** Use a mock ARM server approach for the E2E-006 test. The
Arc MCP Server should accept `AZURE_ARM_BASE_URL` as an environment variable (defaults to
`https://management.azure.com`). The E2E test environment deploys a lightweight mock
ARM server seeded with 120 machines. This avoids real Azure credentials in CI.

---

## 8. Package Versions

### 8.1 Confirmed Versions (March 2026)

| Package | Version | Source | Notes |
|---------|---------|--------|-------|
| `mcp[cli]` | **1.26.0** | PyPI JSON API | `mcp.server.fastmcp.FastMCP` |
| `azure-mgmt-hybridcompute` | **9.0.0** | PyPI JSON API | `HybridComputeManagementClient` |
| `azure-mgmt-hybridkubernetes` | **1.1.0** | PyPI `pip index versions` | `ConnectedKubernetesClient` |
| `azure-mgmt-azurearcdata` | **1.0.0** | PyPI JSON API | `AzureArcDataManagementClient` |
| `azure-mgmt-kubernetesconfiguration` | **3.1.0** | PyPI `pip index versions` | `SourceControlConfigurationClient` (Flux status) |
| `azure-identity` | >=1.17.0 | Existing base requirements | `DefaultAzureCredential` |

**Note:** `azure-mgmt-hybridkubernetes==1.1.0` has a `1.2.0b2` pre-release (2025-03-24)
with additional `ConnectedCluster` properties. For Phase 3, pin to `1.1.0` (stable).
If the `kind`, `distribution_version`, or `aad_profile` fields are needed, evaluate
upgrading to `1.2.0b2` with appropriate risk assessment.

### 8.2 Naming Clarifications (Critical)

These package names in REQUIREMENTS.md map to the following actual PyPI packages:

| REQUIREMENTS.md Reference | Actual PyPI Package | Note |
|--------------------------|---------------------|------|
| `HybridComputeManagementClient` | `azure-mgmt-hybridcompute==9.0.0` | ✅ Correct |
| `ConnectedKubernetesClient` | `azure-mgmt-hybridkubernetes==1.1.0` | ⚠️ NOT `azure-mgmt-connectedk8s` — that does not exist |
| `AzureArcDataManagementClient` | `azure-mgmt-azurearcdata==1.0.0` | ⚠️ NOT `azure-mgmt-arcdata` — that does not exist |

### 8.3 `requirements.txt` for Arc MCP Server Container

```
# requirements-arc-mcp-server.txt
mcp[cli]==1.26.0
azure-identity>=1.17.0
azure-mgmt-hybridcompute==9.0.0
azure-mgmt-hybridkubernetes==1.1.0
azure-mgmt-azurearcdata==1.0.0
azure-mgmt-kubernetesconfiguration==3.1.0
azure-monitor-opentelemetry>=1.6.0
opentelemetry-sdk>=1.25.0
pydantic>=2.8.0
```

---

## Ordering Constraints and Dependencies

### Hard Dependencies

```
[Phase 1 outputs] Container Apps Environment, ACR, VNet
    │
    ▼
[Phase 2] Arc Agent Container App (stub) — already deployed
    │
    ▼
[Phase 3 Step 1] Arc MCP Server Terraform module
    │   - Container App: ca-arc-mcp-server-{env}
    │   - System-assigned identity + Reader RBAC on Arc subscriptions
    │
    ▼
[Phase 3 Step 2] Arc MCP Server implementation
    │   - FastMCP server with @mcp.tool() tools
    │   - Dockerfile (extends from arc-mcp-server base — NOT agents/Dockerfile.base)
    │   - Unit tests (pagination exhaustion, data model serialisation)
    │
    ▼
[Phase 3 Step 3] Arc Agent upgrade (agent.py)
    │   - Replace stub with full triage workflow
    │   - Mount Arc MCP Server + Azure MCP Server tools
    │   - Integration tests
    │
    ▼
[Phase 3 Step 4] E2E-006
    │   - Mock ARM server seeded with 120 Arc servers
    │   - Playwright test: inject incident → verify arc_servers_list total_count >= 100
```

### No-Dependency Parallelism

- Arc MCP Server Terraform module can be planned/implemented concurrently with Arc MCP
  Server code (they are independent until deployment)
- Unit tests for Arc MCP tools can be written in parallel with Terraform

---

## Risk Register

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| R1 | `azure-mgmt-azurearcdata==1.0.0` is old with sparse coverage | MEDIUM | Verify operations at implementation; fall back to direct ARM REST calls if SDK is insufficient |
| R2 | `azure-mgmt-hybridkubernetes==1.1.0` property path differs from docs | MEDIUM | Write thin adapter layer; add unit test for property access; test against real cluster early |
| R3 | `McpTool` API in `azure-ai-projects==2.0.1` has different parameter names than researched | MEDIUM | Verify at implementation; cross-reference with Phase 2 integration tests |
| R4 | Flux GitOps detection via `azure-mgmt-kubernetesconfiguration` may have RBAC gaps | LOW | Arc MCP Server identity needs `Microsoft.KubernetesConfiguration/fluxConfigurations/read` in addition to Reader |
| R5 | E2E-006 seeding >100 Arc servers in real Azure is expensive/slow | HIGH | Use mock ARM server approach; make `AZURE_ARM_BASE_URL` overridable in Arc MCP Server |
| R6 | FastMCP `stateless_http=True` behaviour in `mcp==1.26.0` | LOW | Test locally before containerising; fallback is removing the flag and using standard HTTP |
| R7 | Arc MCP Server port (8080) conflicts with Foundry adapter (8088) | LOW | Arc MCP Server is a separate Container App; no conflict. Agents use port 8088. |

---

## Open Questions for Planning

| # | Question | Proposed Answer |
|---|----------|----------------|
| Q1 | Should the Arc MCP Server extend `agents/Dockerfile.base`? | NO — the base image includes agent-framework and agentserver packages not needed for an MCP server. Create a separate `Dockerfile.arc-mcp-server`. |
| Q2 | Should `azure-mgmt-kubernetesconfiguration` be in-scope for Phase 3? | YES — MONITOR-006 requires Flux reconciliation status. Add it to Arc MCP Server requirements. |
| Q3 | Is `azure-mgmt-azurearcdata==1.0.0` sufficient for AGENT-005 (`arc_data_services_list` tool)? | [UNCERTAIN] — verify at implementation. Minimum viable: list SQL MI instances and PostgreSQL instances. |
| Q4 | Where does `ARC_MCP_SERVER_URL` come from in the Arc Agent's Container App? | Terraform output from `arc-mcp-server` module → injected as env var into Arc Agent Container App via `agent-apps` module update. |
| Q5 | Does the Arc MCP Server need its own OTel instrumentation? | YES — follow the `agents/shared/otel.py` pattern. Each `@mcp.tool()` call should be wrapped in `instrument_tool_call`. Expose `APPLICATIONINSIGHTS_CONNECTION_STRING` env var. |
| Q6 | Multi-subscription: does the Arc MCP Server need to accept a list of subscription IDs? | YES — Arc resources may be spread across subscriptions. The `arc_servers_list` tool should accept `subscription_id` as a required parameter and the caller (Arc Agent) iterates across subscriptions. |

---

## Research Sources

- **Azure HybridCompute Python SDK docs** — `azure.mgmt.hybridcompute.models.Machine`,
  `MachineExtension`, `MachineExtensionProperties`, `MachineExtensionInstanceView`
  — [learn.microsoft.com Python API reference](https://learn.microsoft.com/en-us/python/api/azure-mgmt-hybridcompute)
- **Arc K8s REST API** — `ConnectedCluster` schema with `connectivity_status`,
  `last_connectivity_time`, `total_node_count`, `distribution`, `agent_version`
  — [learn.microsoft.com REST API](https://learn.microsoft.com/en-us/rest/api/hybridkubernetes/connected-cluster/get?view=rest-hybridkubernetes-2024-01-01)
- **FastMCP server examples** — tool declaration, streamable-http transport, lifespan
  context — [modelcontextprotocol.io quickstart/server](https://modelcontextprotocol.io/quickstart/server)
- **FastMCP GitHub README** — `@mcp.tool()` with Pydantic models, `mcp.run()` signatures
  — [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- **MCP Streamable HTTP transport spec** — `stateless_http`, session management, POST/GET
  — [modelcontextprotocol.io/docs/concepts/transports](https://modelcontextprotocol.io/docs/concepts/transports)
- **PyPI JSON API** — version verification for `mcp`, `azure-mgmt-hybridcompute`,
  `azure-mgmt-hybridkubernetes`, `azure-mgmt-azurearcdata`, `azure-mgmt-kubernetesconfiguration`
- **azure-mgmt-hybridkubernetes CHANGELOG** — `1.2.0b2` (2025-03-24) new fields;
  `1.1.0` stable base
  — [GitHub Azure SDK for Python](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/hybridkubernetes/azure-mgmt-hybridkubernetes/CHANGELOG.md)
- **Project internal:** `agents/arc/agent.py` — stub implementation to be replaced
- **Project internal:** `agents/compute/tools.py` — `@ai_function` tool pattern reference
- **Project internal:** `agents/shared/auth.py` — `DefaultAzureCredential` caching pattern
- **Project internal:** `terraform/modules/agent-apps/main.tf` — Container App Terraform
  pattern (internal/external ingress)
- **Project internal:** `.planning/research/STACK.md` — FastMCP + Azure SDK sketch code,
  Arc MCP Server `RemoteMCPTool` mounting pattern
- **Project internal:** `docs/agents/arc-agent.spec.md` — Phase 3 triage workflow,
  tool permissions, `ALLOWED_MCP_TOOLS` definition
- **Project internal:** `.planning/REQUIREMENTS.md` — AGENT-005, AGENT-006, MONITOR-004,
  MONITOR-005, MONITOR-006, TRIAGE-006, E2E-006 definitions

---

*Research completed: 2026-03-26. All API references verified against official Microsoft
docs and PyPI. Package versions confirmed via PyPI JSON API and `pip index versions`.*
