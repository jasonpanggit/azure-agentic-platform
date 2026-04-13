// Shared resource type definitions for all compute resource tabs.
// VMTab, VMDetailPanel, VMSSTab, VMSSDetailPanel, AKSTab, AKSDetailPanel
// all import from here instead of defining types inline.

// ── VM Types (extracted from VMTab.tsx + VMDetailPanel.tsx) ──────────────────

export interface VMRow {
  id: string
  name: string
  resource_group: string
  subscription_id: string
  location: string
  size: string
  os_type: string
  os_name: string
  power_state: string
  vm_type: string  // "Azure VM" | "Arc VM"
  health_state: string
  ama_status: string
  active_alert_count: number
}

export interface EolEntry {
  os_name: string
  eol_date: string | null
  is_eol: boolean | null
  source: string | null
}

export interface ActiveIncident {
  incident_id: string
  severity: string
  title?: string
  created_at: string
  status: string
  investigation_status?: string
}

export interface VMDetail {
  id: string
  name: string
  resource_group: string
  subscription_id: string
  location: string
  size: string
  os_type: string
  os_name: string
  power_state: string
  health_state: string
  health_summary: string | null
  ama_status: string
  vm_type?: string
  tags: Record<string, string>
  active_incidents: ActiveIncident[]
}

export interface Evidence {
  pipeline_status: 'complete' | 'partial' | 'failed' | 'pending'
  collected_at: string | null
  evidence_summary: {
    health_state: string
    recent_changes: RecentChange[]
    metric_anomalies: MetricAnomaly[]
    log_errors: { count: number; sample: string[] }
  } | null
}

export interface RecentChange {
  timestamp: string
  operation: string
  caller: string
  status: string
}

export interface MetricAnomaly {
  metric_name: string
  current_value: number
  threshold: number
  unit: string
}

export interface MetricSeries {
  name: string | null
  unit: string | null
  timeseries: { timestamp: string; average: number | null; maximum: number | null }[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  approval_id?: string
}

// ── VMSS Types ────────────────────────────────────────────────────────────────

export interface VMSSRow {
  id: string                     // ARM resource ID
  name: string
  resource_group: string
  subscription_id: string
  location: string
  sku: string                    // e.g. "Standard_D4s_v3"
  instance_count: number         // total instances
  healthy_instance_count: number
  os_type: string                // "Windows" | "Linux"
  os_image_version: string       // e.g. "Ubuntu 22.04"
  power_state: string            // "running" | "stopped" | "deallocated"
  health_state: string           // "available" | "degraded" | "unavailable" | "unknown"
  autoscale_enabled: boolean
  active_alert_count: number
}

export interface VMSSDetail extends VMSSRow {
  min_count: number
  max_count: number
  upgrade_policy: string         // "Automatic" | "Manual" | "Rolling"
  active_incidents: ActiveIncident[]
  health_summary: string | null
  instances?: VMSSInstance[]
}

export interface VMSSInstance {
  instance_id: string
  name: string
  power_state: string
  health_state: string
  provisioning_state: string
}

// ── AKS Types (stubs — populated fully in Plan 41-2) ─────────────────────────

export interface AKSCluster {
  id: string                     // ARM resource ID
  name: string
  resource_group: string
  subscription_id: string
  location: string
  kubernetes_version: string     // e.g. "1.28.5"
  latest_available_version: string | null  // null if already current
  node_pool_count: number
  node_pools_ready: number
  total_nodes: number
  ready_nodes: number
  system_pod_health: 'healthy' | 'degraded' | 'unknown'
  fqdn: string | null
  network_plugin: string         // "azure" | "kubenet"
  rbac_enabled: boolean
  active_alert_count: number
  // Monitoring addon status — populated by get_aks_detail, absent in list view
  container_insights_enabled?: boolean
  managed_prometheus_enabled?: boolean
  log_analytics_workspace_resource_id?: string | null
}

export interface AKSNodePool {
  name: string
  vm_size: string
  node_count: number
  ready_node_count: number
  mode: 'System' | 'User'
  os_type: 'Linux' | 'Windows'
  min_count: number | null
  max_count: number | null
  provisioning_state: string
}

export interface AKSWorkloadSummary {
  running_pods: number
  crash_loop_pods: number
  pending_pods: number
  namespace_count: number
  source?: 'fallback' | string
}

export interface AKSPodDetail {
  name: string
  namespace: string
  status: string
  node: string
  controller_name: string
  controller_kind: string
}

export interface AKSNamespaceDetail {
  name: string
  running_pods: number
  crash_loop_pods: number
  pending_pods: number
  total_pods: number
}

export interface AKSWorkloadDetail {
  pods: AKSPodDetail[]
  namespaces: AKSNamespaceDetail[]
  total_pods: number
  source: 'kql' | 'kql_empty' | 'unavailable'
  reason?: string
}
