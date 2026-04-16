export type TrafficLight = 'red' | 'yellow' | 'green'

export interface CapacityQuotaItem {
  resource_category: string
  name: string
  quota_name: string
  current_value: number
  limit: number
  usage_pct: number
  available: number
  days_to_exhaustion: number | null
  confidence: string | null
  traffic_light: TrafficLight
  growth_rate_per_day: number | null
  projected_exhaustion_date: string | null
}

export interface CapacityHeadroomResponse {
  subscription_id: string
  location: string
  top_constrained: CapacityQuotaItem[]
  generated_at: string
  snapshot_count: number
  data_note: string | null
}

export interface SubnetHeadroomItem {
  vnet_name: string
  resource_group: string
  subnet_name: string
  address_prefix: string
  total_ips: number
  reserved_ips: number
  ip_config_count: number
  available_ips: number
  usage_pct: number
  traffic_light: TrafficLight
  note: string | null
}

export interface IPSpaceHeadroomResponse {
  subscription_id: string
  subnets: SubnetHeadroomItem[]
  generated_at: string
  duration_ms: number
  note: string | null
}

export interface AKSNodePoolHeadroomItem {
  cluster_name: string
  resource_group: string
  location: string
  pool_name: string
  vm_size: string
  quota_family: string
  current_nodes: number
  max_nodes: number
  available_nodes: number
  usage_pct: number
  traffic_light: TrafficLight
}

export interface AKSHeadroomResponse {
  subscription_id: string
  clusters: AKSNodePoolHeadroomItem[]
  generated_at: string
  duration_ms: number
}
