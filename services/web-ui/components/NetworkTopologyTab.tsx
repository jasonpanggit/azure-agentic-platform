'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
type CytoscapeStylesheet = cytoscape.StylesheetStyle | cytoscape.StylesheetCSS
import CytoscapeComponent from 'react-cytoscapejs'
// @ts-expect-error no types
import coseBilkent from 'cytoscape-cose-bilkent'
import {
  Network,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  MessageSquare,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import NetworkTopologyChatPanel from '@/components/NetworkTopologyChatPanel'

// ---------------------------------------------------------------------------
// Register Cytoscape extensions (module-level, safe for SSR)
// ---------------------------------------------------------------------------

try {
  cytoscape.use(coseBilkent)
} catch { /* already registered */ }

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TopologyNode {
  id: string
  type: string
  label: string
  data: Record<string, unknown>
}

interface TopologyEdge {
  id: string
  source: string
  target: string
  type: string
  data: Record<string, unknown>
}

interface TopologyData {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  issues: Array<Record<string, unknown>>
}

interface PathStep {
  nsg_id: string
  nsg_name: string
  direction: string
  level: string
  result: string
  matching_rule: string
  priority: number
}

interface PathCheckResult {
  verdict: string
  steps: PathStep[]
  blocking_nsg_id: string | null
  source_ip: string
  destination_ip: string
}

// Minimal node/edge shapes used by NodeDetailPanel
interface SimpleNode {
  id: string
  type: string
  data: Record<string, unknown>
  position: { x: number; y: number }
}

interface SimpleEdge {
  id: string
  source: string
  target: string
  type?: string
  label?: string
  data?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 10 * 60 * 1000 // 10 min

// ---------------------------------------------------------------------------
// buildCytoscapeElements
// ---------------------------------------------------------------------------

function buildCytoscapeElements(
  apiNodes: TopologyNode[],
  apiEdges: TopologyEdge[]
): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  // Flat graph — no compound nesting. Every relationship is an edge.
  for (const n of apiNodes) {
    elements.push({
      data: {
        id: n.id,
        label: n.label,
        type: n.type,
        ...n.data,
      },
    })
  }

  for (const e of apiEdges) {
    elements.push({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
        ...e.data,
      },
    })
  }

  return elements
}

// ---------------------------------------------------------------------------
// cytoscapeStylesheet
// ---------------------------------------------------------------------------

const NODE_W = '130px'
const NODE_H = '44px'

const cytoscapeStylesheet: CytoscapeStylesheet[] = [
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      'font-family': 'Inter, system-ui, sans-serif',
      'font-size': '11px',
      'text-valign': 'center',
      'text-halign': 'center',
      'text-wrap': 'ellipsis',
      'text-max-width': '120px',
      color: '#e2e8f0',
      'background-color': '#1e293b',
      'border-width': 1,
      'border-color': '#334155',
      shape: 'roundrectangle',
      width: NODE_W,
      height: NODE_H,
    },
  },
  {
    selector: 'node[type="vnet"]',
    style: {
      'background-color': 'rgba(14, 165, 233, 0.12)',
      'border-color': '#0ea5e9',
      'border-width': 2,
      'font-size': '12px',
      'font-weight': 'bold',
      width: '150px',
      height: '48px',
    },
  },
  {
    selector: 'node[type="subnet"]',
    style: {
      'background-color': 'rgba(51, 65, 85, 0.7)',
      'border-color': '#475569',
      'border-width': 1,
      'font-size': '11px',
    },
  },
  {
    selector: 'node[type="nsg"]',
    style: {
      'background-color': '#1e293b',
      'border-color': '#64748b',
    },
  },
  {
    selector: 'node[type="nsg"][health="yellow"]',
    style: { 'border-color': '#f59e0b', 'border-width': 2 },
  },
  {
    selector: 'node[type="nsg"][health="red"]',
    style: { 'border-color': '#ef4444', 'border-width': 2 },
  },
  {
    selector: 'node[type="vm"]',
    style: { 'background-color': 'rgba(16, 185, 129, 0.08)', 'border-color': '#10b981' },
  },
  {
    selector: 'node[type="lb"]',
    style: { 'background-color': 'rgba(139, 92, 246, 0.08)', 'border-color': '#8b5cf6' },
  },
  {
    selector: 'node[type="pe"]',
    style: { 'background-color': 'rgba(139, 92, 246, 0.06)', 'border-color': '#a78bfa' },
  },
  {
    selector: 'node[type="gateway"]',
    style: { 'background-color': 'rgba(245, 158, 11, 0.08)', 'border-color': '#f59e0b' },
  },
  {
    selector: 'node[type="firewall"]',
    style: { 'background-color': 'rgba(239, 68, 68, 0.08)', 'border-color': '#ef4444' },
  },
  {
    selector: 'node[type="appgw"]',
    style: { 'background-color': 'rgba(139, 92, 246, 0.08)', 'border-color': '#c084fc' },
  },
  {
    selector: 'node[type="vmss"]',
    style: { 'background-color': 'rgba(14, 165, 233, 0.06)', 'border-color': '#38bdf8' },
  },
  {
    selector: 'node[type="aks"]',
    style: { 'background-color': 'rgba(14, 165, 233, 0.08)', 'border-color': '#0ea5e9', 'border-width': 2 },
  },
  // Edges
  {
    selector: 'edge',
    style: {
      'curve-style': 'bezier',
      'line-color': '#475569',
      width: 1,
      'target-arrow-color': '#475569',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.7,
      'font-size': '10px',
      color: '#94a3b8',
    },
  },
  {
    selector: 'edge[type="peering"]',
    style: {
      'line-color': '#0ea5e9',
      'target-arrow-color': '#0ea5e9',
      width: 2,
      'line-style': 'solid',
    },
  },
  {
    selector: 'edge[type="peering-disconnected"]',
    style: {
      'line-color': '#ef4444',
      'target-arrow-color': '#ef4444',
      width: 2,
      'line-style': 'dashed',
    },
  },
  {
    selector: 'edge[type="asymmetry"]',
    style: {
      'line-color': '#ef4444',
      'target-arrow-color': '#ef4444',
      width: 2.5,
      'line-style': 'dashed',
    },
  },
  {
    selector: 'edge[type="subnet-vm"]',
    style: { 'line-color': '#10b981', 'line-style': 'dashed', width: 1 },
  },
  {
    selector: 'edge[type="subnet-nsg"]',
    style: { 'line-color': '#64748b', 'line-style': 'dotted', width: 1 },
  },
  // Highlight states
  {
    selector: '.chat-highlighted',
    style: {
      'border-color': '#f97316',
      'border-width': 3,
      'background-color': 'rgba(249, 115, 22, 0.12)',
    },
  },
  {
    selector: '.path-blocked',
    style: {
      'border-color': '#ef4444',
      'border-width': 3,
      'background-color': 'rgba(239, 68, 68, 0.15)',
    },
  },
  {
    selector: '.dimmed',
    style: { opacity: 0.2 },
  },
  {
    selector: ':selected',
    style: {
      'border-color': '#60a5fa',
      'border-width': 2,
    },
  },
]

// ---------------------------------------------------------------------------
// Helper: map API node type → NodeDetailPanel type suffix
// ---------------------------------------------------------------------------

function toNodePanelType(apiType: string): string {
  const mapping: Record<string, string> = {
    vnet: 'vnetNode',
    subnet: 'subnetNode',
    nsg: 'nsgNode',
    lb: 'lbNode',
    pe: 'peNode',
    gateway: 'gatewayNode',
    vm: 'vmNode',
    vmss: 'vmssNode',
    aks: 'aksNode',
    firewall: 'firewallNode',
    appgw: 'appGatewayNode',
  }
  return mapping[apiType] ?? apiType
}

// ---------------------------------------------------------------------------
// NodeDetailPanel components
// ---------------------------------------------------------------------------

function FieldRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-2" style={{ borderBottom: '1px solid var(--border)' }}>
      <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="text-sm" style={{ color: 'var(--text-primary)' }}>{value}</span>
    </div>
  )
}

function HealthBadge({ health }: { health: string }) {
  const labels: Record<string, string> = { green: 'OK', yellow: 'WARN', red: 'BLOCK' }
  const accent = `var(--accent-${health})`
  return (
    <span
      className="px-1.5 py-px rounded-full text-[11px] font-semibold uppercase tracking-wide"
      style={{
        background: `color-mix(in srgb, ${accent} 15%, transparent)`,
        color: accent,
        border: `1px solid color-mix(in srgb, ${accent} 30%, transparent)`,
      }}
    >
      {labels[health] ?? health}
    </span>
  )
}

function NsgRulesTable({ rules }: { rules: Array<Record<string, unknown>> }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {['Priority', 'Name', 'Dir', 'Access', 'Proto', 'Source', 'Dest', 'Ports'].map((h) => (
              <th key={h} className="text-left pb-1 pr-2 font-medium" style={{ color: 'var(--text-muted)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rules.map((r, i) => (
            <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
              <td className="py-1 pr-2" style={{ color: 'var(--text-secondary)' }}>{r.priority as string}</td>
              <td className="py-1 pr-2 font-mono" style={{ color: 'var(--text-primary)' }}>{r.name as string}</td>
              <td className="py-1 pr-2" style={{ color: 'var(--text-secondary)' }}>{r.direction as string}</td>
              <td className="py-1 pr-2">
                <span style={{ color: (r.access as string)?.toLowerCase() === 'allow' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                  {r.access as string}
                </span>
              </td>
              <td className="py-1 pr-2" style={{ color: 'var(--text-secondary)' }}>{r.protocol as string}</td>
              <td className="py-1 pr-2 font-mono" style={{ color: 'var(--text-muted)' }}>{r.source as string}</td>
              <td className="py-1 pr-2 font-mono" style={{ color: 'var(--text-muted)' }}>{r.destination as string}</td>
              <td className="py-1 font-mono" style={{ color: 'var(--text-muted)' }}>{r.ports as string}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface NodeDetailPanelProps {
  node: SimpleNode | null
  edge: SimpleEdge | null
  open: boolean
  onClose: () => void
}

function NodeDetailPanel({ node, edge, open, onClose }: NodeDetailPanelProps) {
  if (!open) return null

  const renderNodeContent = () => {
    if (!node) return null
    const d = node.data

    switch (node.type) {
      case 'nsgNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>NSG Details</p>
            <FieldRow label="Name" value={d.label as string} />
            <FieldRow label="Health" value={<HealthBadge health={(d.health as string) ?? 'green'} />} />
            {d.ruleCount != null && <FieldRow label="Rule Count" value={String(d.ruleCount)} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
            {Array.isArray(d.rules) && d.rules.length > 0 ? (
              <>
                <p className="text-xs font-semibold mt-4 mb-1" style={{ color: 'var(--text-secondary)' }}>Security Rules</p>
                <NsgRulesTable rules={d.rules as Array<Record<string, unknown>>} />
              </>
            ) : (
              <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
                No custom security rules — only Azure default rules apply.
              </p>
            )}
          </>
        )

      case 'vnetNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>VNet Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.addressSpace && <FieldRow label="Address Space" value={<span className="font-mono">{d.addressSpace as string}</span>} />}
            {(d.subscriptionId || d.subscription) && <FieldRow label="Subscription" value={(d.subscriptionId || d.subscription) as string} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            {d.peeringCount != null && <FieldRow label="Peering Count" value={String(d.peeringCount)} />}
          </>
        )

      case 'subnetNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Subnet Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.cidr && <FieldRow label="CIDR" value={<span className="font-mono">{d.cidr as string}</span>} />}
            <FieldRow label="NSG" value={(d.nsgId as string) || 'None'} />
            <FieldRow label="Route Table" value={(d.routeTable as string) || 'None'} />
          </>
        )

      case 'lbNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Load Balancer Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.sku && <FieldRow label="SKU" value={d.sku as string} />}
            <FieldRow label="Public IP" value={(d.publicIp as string) || 'Internal'} />
          </>
        )

      case 'peNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Private Endpoint Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.targetService && <FieldRow label="Target Service" value={d.targetService as string} />}
            <FieldRow label="Private IP" value={(d.privateIp as string) || '—'} />
            <FieldRow label="Connection State" value={(d.connectionState as string) || '—'} />
          </>
        )

      case 'gatewayNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Gateway Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.gatewayType && <FieldRow label="Type" value={d.gatewayType as string} />}
            {d.sku && <FieldRow label="SKU" value={d.sku as string} />}
            <FieldRow label="BGP" value={(d.bgpEnabled as boolean) ? 'Enabled' : 'Disabled'} />
          </>
        )

      case 'vmNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Virtual Machine</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.vmSize && <FieldRow label="Size" value={<span className="font-mono">{d.vmSize as string}</span>} />}
            {d.osType && <FieldRow label="OS Type" value={d.osType as string} />}
            {d.privateIp && <FieldRow label="Private IP" value={<span className="font-mono">{d.privateIp as string}</span>} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
          </>
        )

      case 'vmssNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>VM Scale Set</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.sku && <FieldRow label="SKU" value={<span className="font-mono">{d.sku as string}</span>} />}
            {d.capacity != null && <FieldRow label="Capacity" value={`${d.capacity} instances`} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
          </>
        )

      case 'aksNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>AKS Cluster</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.kubernetesVersion && <FieldRow label="Kubernetes Version" value={<span className="font-mono">{d.kubernetesVersion as string}</span>} />}
            {d.nodeCount != null && <FieldRow label="Node Count" value={String(d.nodeCount)} />}
            {d.provisioningState && <FieldRow label="State" value={d.provisioningState as string} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
          </>
        )

      case 'firewallNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Azure Firewall</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.skuTier && <FieldRow label="SKU Tier" value={d.skuTier as string} />}
            {d.threatIntelMode && <FieldRow label="Threat Intel Mode" value={d.threatIntelMode as string} />}
            {d.privateIp && <FieldRow label="Private IP" value={<span className="font-mono">{d.privateIp as string}</span>} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
          </>
        )

      case 'appGatewayNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Application Gateway</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.sku && <FieldRow label="SKU" value={d.sku as string} />}
            {d.skuTier && <FieldRow label="Tier" value={d.skuTier as string} />}
            {d.capacity != null && <FieldRow label="Capacity" value={String(d.capacity)} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
          </>
        )

      default:
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Node Details</p>
            {Object.entries(d).map(([k, v]) => (
              <FieldRow key={k} label={k} value={String(v)} />
            ))}
          </>
        )
    }
  }

  const renderEdgeContent = () => {
    if (!edge) return null
    const isPeering = edge.type === 'peering' || edge.type === 'peering-disconnected'
    const isAsymmetry = edge.type === 'asymmetry'
    return (
      <>
        <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>
          {isPeering ? 'VNet Peering' : isAsymmetry ? 'NSG Asymmetry' : (edge.label as string) || 'Connection Details'}
        </p>
        <FieldRow label="Source" value={<span className="font-mono text-xs">{edge.source}</span>} />
        <FieldRow label="Target" value={<span className="font-mono text-xs">{edge.target}</span>} />
        <FieldRow label="Type" value={edge.type ?? '—'} />
        {isPeering && edge.data?.peeringState && (
          <FieldRow
            label="Peering State"
            value={
              <span style={{ color: String(edge.data.peeringState).toLowerCase() === 'connected' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                {String(edge.data.peeringState)}
              </span>
            }
          />
        )}
        {isPeering && (
          <>
            <FieldRow label="Forwarded Traffic" value={edge.data?.allowForwardedTraffic ? 'Allowed' : 'Blocked'} />
            <FieldRow label="Gateway Transit" value={edge.data?.allowGatewayTransit ? 'Allowed' : 'Blocked'} />
          </>
        )}
        {isAsymmetry && edge.data?.description && (
          <div
            className="mt-3 rounded p-3 text-xs"
            style={{
              background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
              border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
              color: 'var(--accent-red)',
            }}
          >
            <p className="font-semibold mb-1">Asymmetric NSG Rule</p>
            <p>{String(edge.data.description)}</p>
            <p className="mt-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
              The source NSG allows outbound on port {String(edge.data.port ?? '')}/TCP, but the destination NSG has no matching inbound allow rule. Traffic will be silently dropped at the destination.
            </p>
          </div>
        )}
        {!isPeering && !isAsymmetry && edge.data?.issue && (
          <div
            className="mt-3 rounded p-3 text-xs"
            style={{
              background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
              border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
              color: 'var(--accent-red)',
            }}
          >
            <p className="font-semibold mb-1">Issue Detected</p>
            <p>{String(edge.data.issue)}</p>
          </div>
        )}
      </>
    )
  }

  const title = edge
    ? ((edge.label as string) || 'Connection Details')
    : node
    ? (node.data.label as string)
    : 'Details'

  return (
    <Sheet open={open} onOpenChange={onClose}>
      <SheetContent side="right" className="w-[380px] sm:w-[440px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
        </SheetHeader>
        {node && renderNodeContent()}
        {edge && renderEdgeContent()}
      </SheetContent>
    </Sheet>
  )
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function NetworkTopologyTab() {
  const cyRef = useRef<Core | null>(null)
  const [elements, setElements] = useState<ElementDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [topologyData, setTopologyData] = useState<TopologyData | null>(null)

  // Drill-down state
  const [selectedNode, setSelectedNode] = useState<SimpleNode | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<SimpleEdge | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // Path checker state
  const [pathSheetOpen, setPathSheetOpen] = useState(false)
  const [pathSource, setPathSource] = useState('')
  const [pathDest, setPathDest] = useState('')
  const [pathPort, setPathPort] = useState('443')
  const [pathProtocol, setPathProtocol] = useState('TCP')
  const [pathResult, setPathResult] = useState<PathCheckResult | null>(null)
  const [pathLoading, setPathLoading] = useState(false)
  const [pathError, setPathError] = useState<string | null>(null)

  // Chat panel state
  const [chatOpen, setChatOpen] = useState(false)
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set())

  // Summary counts
  const vnetCount = useMemo(() => topologyData?.nodes.filter((n) => n.type === 'vnet').length ?? 0, [topologyData])
  const nsgCount = useMemo(() => topologyData?.nodes.filter((n) => n.type === 'nsg').length ?? 0, [topologyData])
  const issueCount = useMemo(() => topologyData?.issues.length ?? 0, [topologyData])
  const vmCount = useMemo(() => topologyData?.nodes.filter((n) => n.type === 'vm').length ?? 0, [topologyData])
  const aksCount = useMemo(() => topologyData?.nodes.filter((n) => n.type === 'aks').length ?? 0, [topologyData])
  const firewallCount = useMemo(() => topologyData?.nodes.filter((n) => n.type === 'firewall').length ?? 0, [topologyData])

  // nodeIndex: resourceId (lowercased) and short name (lowercased) → node id
  const nodeIndex = useMemo(() => {
    const m = new Map<string, string>()
    topologyData?.nodes.forEach((n) => {
      m.set(n.id.toLowerCase(), n.id)
      m.set(n.label.toLowerCase(), n.id)
    })
    return m
  }, [topologyData])

  // topologyContext for the chat panel
  const topologyContext = useMemo(() => ({
    nodeCount: topologyData?.nodes.length ?? 0,
    edgeCount: topologyData?.edges.length ?? 0,
    selectedNodeId: selectedNode?.id,
  }), [topologyData, selectedNode])

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/proxy/network/topology')
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d?.error ?? `HTTP ${res.status}`)
      }
      const data: TopologyData = await res.json()
      setTopologyData(data)
      setElements(buildCytoscapeElements(data.nodes, data.edges))

      // If the backend returned zero nodes it may still be warming up.
      // Schedule one automatic retry after 8 seconds.
      if (data.nodes.length === 0) {
        setTimeout(() => {
          setLoading(true)
          fetch('/api/proxy/network/topology')
            .then((r) => r.json())
            .then((retryData: TopologyData) => {
              if (retryData.nodes && retryData.nodes.length > 0) {
                setTopologyData(retryData)
                setElements(buildCytoscapeElements(retryData.nodes, retryData.edges))
              }
            })
            .catch(() => { /* silent — next interval will retry */ })
            .finally(() => setLoading(false))
        }, 8000)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  const handlePathCheck = useCallback(async () => {
    if (!pathSource || !pathDest) return
    setPathLoading(true)
    setPathResult(null)
    setPathError(null)
    try {
      const res = await fetch('/api/proxy/network/topology/path-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_resource_id: pathSource,
          destination_resource_id: pathDest,
          port: parseInt(pathPort, 10),
          protocol: pathProtocol,
        }),
      })
      const data: PathCheckResult = await res.json()
      setPathResult(data)

      const cy = cyRef.current
      if (cy && data.blocking_nsg_id) {
        cy.elements().addClass('dimmed')
        cy.getElementById(data.blocking_nsg_id).removeClass('dimmed').addClass('path-blocked')
      } else if (cy && data.verdict === 'allowed') {
        cy.edges().style({ 'line-color': '#10b981', width: 2 })
      }
    } catch (err) {
      setPathError(err instanceof Error ? err.message : 'Path check failed')
    } finally {
      setPathLoading(false)
    }
  }, [pathSource, pathDest, pathPort, pathProtocol])

  const handleClearPathCheck = useCallback(() => {
    setPathResult(null)
    const cy = cyRef.current
    if (cy) {
      cy.elements().removeClass('dimmed path-blocked')
      cy.edges().removeStyle('line-color width')
    }
    if (topologyData) {
      setElements(buildCytoscapeElements(topologyData.nodes, topologyData.edges))
    }
  }, [topologyData])

  // Resource options for path checker selects
  const resourceOptions = useMemo(
    () =>
      topologyData?.nodes
        .filter((n) => ['subnet', 'nsg', 'vnet', 'vm'].includes(n.type))
        .map((n) => ({ id: n.id, label: `${n.label} (${n.type.toUpperCase()})` })) ?? [],
    [topologyData]
  )

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Network size={20} style={{ color: 'var(--accent-blue)' }} />
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
            Network Topology
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={chatOpen ? 'default' : 'outline'}
            size="sm"
            onClick={() => setChatOpen((v) => !v)}
          >
            <MessageSquare size={14} />
            Ask AI
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchData()}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </Button>
          <Sheet open={pathSheetOpen} onOpenChange={setPathSheetOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="sm">
                Path Checker
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>NSG Path Check</SheetTitle>
              </SheetHeader>
              <div className="flex flex-col gap-4 mt-4">
                <div>
                  <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
                    Source Resource
                  </label>
                  <Select value={pathSource} onValueChange={setPathSource}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select source" />
                    </SelectTrigger>
                    <SelectContent>
                      {resourceOptions.map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
                    Destination Resource
                  </label>
                  <Select value={pathDest} onValueChange={setPathDest}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select destination" />
                    </SelectTrigger>
                    <SelectContent>
                      {resourceOptions.map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
                      Port
                    </label>
                    <Input
                      type="number"
                      value={pathPort}
                      onChange={(e) => setPathPort(e.target.value)}
                      placeholder="443"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--text-secondary)' }}>
                      Protocol
                    </label>
                    <Select value={pathProtocol} onValueChange={setPathProtocol}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="TCP">TCP</SelectItem>
                        <SelectItem value="UDP">UDP</SelectItem>
                        <SelectItem value="ICMP">ICMP</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <Button onClick={handlePathCheck} disabled={pathLoading || !pathSource || !pathDest}>
                  {pathLoading ? 'Checking...' : 'Check Path'}
                </Button>

                {/* Verdict display */}
                {pathError && (
                  <div
                    className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
                    style={{
                      background: 'color-mix(in srgb, var(--accent-yellow) 10%, transparent)',
                      borderColor: 'color-mix(in srgb, var(--accent-yellow) 30%, transparent)',
                      color: 'var(--accent-yellow)',
                    }}
                  >
                    <XCircle size={14} />
                    {pathError}
                  </div>
                )}
                {pathResult && pathResult.verdict === 'allowed' && (
                  <div
                    className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
                    style={{
                      background: 'color-mix(in srgb, var(--accent-green) 10%, transparent)',
                      borderColor: 'color-mix(in srgb, var(--accent-green) 30%, transparent)',
                      color: 'var(--accent-green)',
                    }}
                  >
                    <CheckCircle size={14} />
                    Traffic Allowed
                  </div>
                )}
                {pathResult && pathResult.verdict === 'blocked' && (
                  <div
                    className="rounded border px-3 py-2 text-sm"
                    style={{
                      background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
                      borderColor: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
                      color: 'var(--accent-red)',
                    }}
                  >
                    <div className="flex items-center gap-2 font-semibold mb-1">
                      <XCircle size={14} />
                      Traffic Blocked
                    </div>
                    {pathResult.steps.filter(s => s.result === 'Deny').map((step, idx) => (
                      <p key={idx} className="text-xs mt-1" style={{ color: 'var(--accent-red)' }}>
                        Blocked by <span className="font-semibold">{step.nsg_name || pathResult.blocking_nsg_id}</span> ({step.direction} rule &quot;{step.matching_rule}&quot;, priority {step.priority}) — this rule explicitly denies port {pathPort}/{pathProtocol} traffic.
                      </p>
                    ))}
                  </div>
                )}

                {/* Step-by-step timeline */}
                {pathResult && pathResult.steps.length > 0 && (
                  <div className="flex flex-col gap-2 mt-2">
                    {pathResult.steps.map((step, idx) => (
                      <div key={idx} className="flex items-start gap-2 text-[11px]">
                        <span style={{ color: 'var(--text-muted)' }}>[{idx + 1}]</span>
                        <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>
                          {step.nsg_name}
                        </span>
                        <span style={{ color: 'var(--text-secondary)' }}>
                          ({step.direction}, {step.level})
                        </span>
                        {step.result === 'Allow' ? (
                          <span className="flex items-center gap-1" style={{ color: 'var(--accent-green)' }}>
                            <CheckCircle size={12} /> Allow
                          </span>
                        ) : (
                          <span className="flex items-center gap-1" style={{ color: 'var(--accent-red)' }}>
                            <XCircle size={12} /> Deny
                          </span>
                        )}
                        <span className="font-mono" style={{ color: 'var(--text-muted)' }}>
                          &quot;{step.matching_rule}&quot; (pri {step.priority})
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {pathResult && (
                  <Button variant="outline" size="sm" onClick={handleClearPathCheck}>
                    Clear
                  </Button>
                )}

                {!pathResult && !pathLoading && (
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    Select source, destination, port, and protocol to check connectivity.
                  </p>
                )}
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>

      {/* Summary pills */}
      <div className="flex items-center gap-3">
        <span
          className="text-xs px-2 py-1 rounded"
          style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
        >
          VNets: {vnetCount}
        </span>
        <span
          className="text-xs px-2 py-1 rounded"
          style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
        >
          NSGs: {nsgCount}
        </span>
        <span
          className="text-xs px-2 py-1 rounded"
          style={{
            background: issueCount > 0
              ? 'color-mix(in srgb, var(--accent-red) 15%, transparent)'
              : 'var(--bg-subtle)',
            color: issueCount > 0 ? 'var(--accent-red)' : 'var(--text-secondary)',
          }}
        >
          Issues: {issueCount}
        </span>
        {vmCount > 0 && (
          <span className="text-xs px-2 py-1 rounded" style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}>
            VMs: {vmCount}
          </span>
        )}
        {aksCount > 0 && (
          <span className="text-xs px-2 py-1 rounded" style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}>
            AKS: {aksCount}
          </span>
        )}
        {firewallCount > 0 && (
          <span className="text-xs px-2 py-1 rounded" style={{ background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)', color: 'var(--accent-red)' }}>
            Firewalls: {firewallCount}
          </span>
        )}
        <span className="text-[11px] ml-2" style={{ color: 'var(--text-muted)' }}>
          · Click any node or connection to inspect details
        </span>
      </div>

      {/* Error */}
      {error && (
        <div
          className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            borderColor: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
            color: 'var(--accent-red)',
          }}
        >
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Canvas */}
      {loading && !topologyData && (
        <div
          className="flex flex-col items-center justify-center gap-3"
          style={{ height: 'calc(100vh - 220px)', color: 'var(--text-secondary)' }}
        >
          <RefreshCw size={24} className="animate-spin" />
          <span className="text-sm">Loading network topology...</span>
        </div>
      )}

      {!loading && !error && topologyData && topologyData.nodes.length === 0 && (
        <div
          className="flex flex-col items-center justify-center gap-3"
          style={{ height: 'calc(100vh - 220px)', color: 'var(--text-muted)' }}
        >
          <Network size={40} />
          <span className="text-sm">No network resources found in the current subscriptions.</span>
        </div>
      )}

      {topologyData && topologyData.nodes.length > 0 && (
        <div className="flex" style={{ height: 'calc(100vh - 220px)' }}>
          <div style={{ flex: '1 1 0', minWidth: 0, background: 'var(--bg-canvas)' }}>
            <CytoscapeComponent
              elements={elements}
              stylesheet={cytoscapeStylesheet}
              layout={{
                name: 'cose-bilkent',
                animate: false,
                nodeDimensionsIncludeLabels: true,
                randomize: false,
                idealEdgeLength: 120,
                nodeRepulsion: 12000,
                nodeOverlap: 20,
                padding: 40,
                gravityRangeCompound: 1.5,
                gravityCompound: 1.0,
                gravity: 0.25,
              } as cytoscape.LayoutOptions}
              cy={(cy: Core) => {
                cyRef.current = cy
                cy.on('tap', 'node', (evt) => {
                  const nodeData = evt.target.data() as Record<string, unknown>
                  setSelectedNode({
                    id: nodeData.id as string,
                    type: toNodePanelType(nodeData.type as string),
                    data: nodeData,
                    position: { x: 0, y: 0 },
                  })
                  setSelectedEdge(null)
                  setDetailOpen(true)
                })
                cy.on('tap', 'edge', (evt) => {
                  const edgeData = evt.target.data() as Record<string, unknown>
                  setSelectedEdge({
                    id: edgeData.id as string,
                    source: edgeData.source as string,
                    target: edgeData.target as string,
                    type: edgeData.type as string,
                    data: edgeData,
                  })
                  setSelectedNode(null)
                  setDetailOpen(true)
                })
                cy.on('tap', (evt) => {
                  if (evt.target === cy) setDetailOpen(false)
                })
              }}
              style={{ width: '100%', height: '100%', background: 'var(--bg-canvas)' }}
            />
          </div>
          {chatOpen && (
            <div style={{ width: 360, flexShrink: 0 }}>
              <NetworkTopologyChatPanel
                subscriptionIds={[]}
                topologyContext={topologyContext}
                nodeIndex={nodeIndex}
                onHighlight={(ids) => {
                  setHighlightedNodeIds(ids)
                  const cy = cyRef.current
                  if (!cy) return
                  cy.nodes().removeClass('chat-highlighted')
                  if (ids.size > 0) {
                    cy.nodes().filter((n) => ids.has(n.id())).addClass('chat-highlighted')
                  }
                }}
                onClose={() => setChatOpen(false)}
              />
            </div>
          )}
        </div>
      )}

      <NodeDetailPanel
        node={selectedNode}
        edge={selectedEdge}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  )
}
