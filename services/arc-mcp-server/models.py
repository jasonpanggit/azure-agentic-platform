"""Pydantic response models for the Arc MCP Server tools (AGENT-005, AGENT-006).

All tool return types are Pydantic BaseModel subclasses. FastMCP serialises
them to JSON automatically. Optional fields use None defaults to avoid
ValidationError on real Azure SDK data where fields may be absent.

Design rules:
  - Never raise ValidationError on real Azure ARM data.
  - Use Optional[str] for all nullable ARM string fields.
  - Use bool = False for computed flags (prolonged_disconnection, flux_detected).
  - total_count MUST equal len(the_list) — enforced by list tools.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Arc Servers (Microsoft.HybridCompute/machines)
# ---------------------------------------------------------------------------


class ArcExtensionHealth(BaseModel):
    """Health status of a single Arc machine extension (MONITOR-005).

    Covers: AMA, VM Insights (DependencyAgent), Change Tracking, Policy.
    """

    name: str
    publisher: Optional[str] = None
    extension_type: Optional[str] = None
    provisioning_state: Optional[str] = None  # "Succeeded" | "Failed" | "Creating"
    type_handler_version: Optional[str] = None
    auto_upgrade_enabled: Optional[bool] = None
    # From instance_view.status
    status_code: Optional[str] = None          # e.g. "ProvisioningState/succeeded"
    status_level: Optional[str] = None         # "Info" | "Warning" | "Error"
    status_display: Optional[str] = None       # human-readable
    status_message: Optional[str] = None       # detailed message


class ArcServerSummary(BaseModel):
    """Summary of a single Arc-enabled server (MONITOR-004).

    Connectivity status, agent version, OS info, and prolonged disconnection
    flag (MONITOR-004). Resource group is extracted from ARM resource ID.
    """

    resource_id: str
    name: str
    resource_group: str
    subscription_id: str
    location: Optional[str] = None
    status: Optional[str] = None               # "Connected" | "Disconnected" | "Error"
    last_status_change: Optional[str] = None   # ISO 8601 datetime string
    agent_version: Optional[str] = None
    os_name: Optional[str] = None
    os_type: Optional[str] = None              # "windows" | "linux"
    os_version: Optional[str] = None
    kind: Optional[str] = None                 # "AVS" | "HCI" | "SCVMM" | "VMware" etc.
    provisioning_state: Optional[str] = None
    # Computed flag: True when status==Disconnected AND duration > threshold (MONITOR-004)
    prolonged_disconnection: bool = False


class ArcServersListResult(BaseModel):
    """Result of arc_servers_list tool (AGENT-006 — total_count required)."""

    subscription_id: str
    resource_group: Optional[str] = None
    servers: List[ArcServerSummary]
    total_count: int  # MUST equal len(servers) — AGENT-006


class ArcServerDetail(BaseModel):
    """Detailed view of a single Arc server including extensions (MONITOR-005)."""

    resource_id: str
    name: str
    resource_group: str
    subscription_id: str
    location: Optional[str] = None
    status: Optional[str] = None
    last_status_change: Optional[str] = None
    agent_version: Optional[str] = None
    os_name: Optional[str] = None
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    kind: Optional[str] = None
    provisioning_state: Optional[str] = None
    prolonged_disconnection: bool = False
    extensions: List[ArcExtensionHealth] = []


class ArcExtensionsListResult(BaseModel):
    """Result of arc_extensions_list tool (MONITOR-005)."""

    resource_id: str
    machine_name: str
    resource_group: str
    subscription_id: str
    extensions: List[ArcExtensionHealth]
    total_count: int  # MUST equal len(extensions) — AGENT-006


# ---------------------------------------------------------------------------
# Arc Kubernetes (Microsoft.Kubernetes/connectedClusters)
# ---------------------------------------------------------------------------


class ArcFluxConfiguration(BaseModel):
    """Flux GitOps configuration entry for an Arc K8s cluster (MONITOR-006)."""

    name: str
    compliance_state: Optional[str] = None    # "Compliant" | "NonCompliant" | "Pending"
    provisioning_state: Optional[str] = None
    source_kind: Optional[str] = None         # "GitRepository" | "Bucket"
    repository_url: Optional[str] = None
    branch: Optional[str] = None
    sync_interval_in_seconds: Optional[int] = None


class ArcK8sSummary(BaseModel):
    """Summary of a single Arc-enabled Kubernetes cluster (MONITOR-006)."""

    resource_id: str
    name: str
    resource_group: str
    subscription_id: str
    location: Optional[str] = None
    connectivity_status: Optional[str] = None  # "Connected" | "Offline" | "Expired"
    last_connectivity_time: Optional[str] = None
    kubernetes_version: Optional[str] = None
    distribution: Optional[str] = None         # "AKS" | "k3s" | "openshift" etc.
    total_node_count: Optional[int] = None
    total_core_count: Optional[int] = None
    agent_version: Optional[str] = None
    provisioning_state: Optional[str] = None
    # Flux detection (MONITOR-006)
    flux_detected: bool = False
    flux_configurations: List[ArcFluxConfiguration] = []


class ArcK8sListResult(BaseModel):
    """Result of arc_k8s_list tool (AGENT-006 — total_count required)."""

    subscription_id: str
    resource_group: Optional[str] = None
    clusters: List[ArcK8sSummary]
    total_count: int  # MUST equal len(clusters) — AGENT-006


# ---------------------------------------------------------------------------
# Arc Data Services (Microsoft.AzureArcData)
# ---------------------------------------------------------------------------


class ArcSqlMiSummary(BaseModel):
    """Summary of a single Arc-enabled SQL Managed Instance."""

    resource_id: str
    name: str
    resource_group: str
    subscription_id: str
    location: Optional[str] = None
    state: Optional[str] = None
    edition: Optional[str] = None
    v_cores: Optional[int] = None
    provisioning_state: Optional[str] = None


class ArcSqlMiListResult(BaseModel):
    """Result of arc_data_sql_mi_list tool (AGENT-006 — total_count required)."""

    subscription_id: str
    instances: List[ArcSqlMiSummary]
    total_count: int  # MUST equal len(instances) — AGENT-006


class ArcPostgreSQLSummary(BaseModel):
    """Summary of a single Arc-enabled PostgreSQL instance."""

    resource_id: str
    name: str
    resource_group: str
    subscription_id: str
    location: Optional[str] = None
    state: Optional[str] = None
    provisioning_state: Optional[str] = None


class ArcPostgreSQLListResult(BaseModel):
    """Result of arc_data_postgresql_list tool (AGENT-006 — total_count required)."""

    subscription_id: str
    instances: List[ArcPostgreSQLSummary]
    total_count: int  # MUST equal len(instances) — AGENT-006
