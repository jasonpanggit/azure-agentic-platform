'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import {
  ReactFlow,
  Handle,
  Position,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeProps,
  useNodesState,
  useEdgesState,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import ELK from 'elkjs/lib/elk.bundled.js'
import {
  Shield,
  Network,
  Scale,
  Lock,
  Globe,
  Waypoints,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Server,
  Layers,
  Container,
  Flame,
  AppWindow,
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
// NodeDetailPanel
// ---------------------------------------------------------------------------

interface NodeDetailPanelProps {
  node: Node | null
  edge: Edge | null
  open: boolean
  onClose: () => void
}

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
// Constants
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 10 * 60 * 1000 // 10 min

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

// ---------------------------------------------------------------------------
// ELK Layout
// ---------------------------------------------------------------------------

const elk = new ELK()

async function computeLayout(
  rfNodes: Node[],
  rfEdges: Edge[]
): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const graph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '40',
      'elk.layered.spacing.baseValue': '60',
    },
    children: rfNodes.map((n) => ({
      id: n.id,
      width: (n.width as number) ?? 200,
      height: (n.height as number) ?? 80,
    })),
    edges: rfEdges.map((e) => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    })),
  }
  const layout = await elk.layout(graph)
  const positionedNodes = rfNodes.map((n) => {
    const elkNode = layout.children?.find((c) => c.id === n.id)
    return elkNode
      ? { ...n, position: { x: elkNode.x ?? 0, y: elkNode.y ?? 0 } }
      : n
  })
  return { nodes: positionedNodes, edges: rfEdges }
}

// ---------------------------------------------------------------------------
// Custom Node Components
// ---------------------------------------------------------------------------

function VNetNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-4 min-w-[280px]"
      style={{
        border: '2px solid var(--accent-blue)',
        background: 'color-mix(in srgb, var(--accent-blue) 5%, var(--bg-surface))',
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2 mb-1">
        <Network size={16} style={{ color: 'var(--accent-blue)' }} />
        <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      {!!(data.addressSpace) && (
        <span
          className="text-xs font-mono"
          style={{ color: 'var(--text-secondary)' }}
        >
          {data.addressSpace as string}
        </span>
      )}
      {!!(data.subscription) && (
        <span
          className="block text-[10px] mt-1"
          style={{ color: 'var(--text-muted)' }}
        >
          {data.subscription as string}
        </span>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function SubnetNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-md p-2"
      style={{
        width: 180,
        border: '1px solid var(--border)',
        background: 'var(--bg-surface)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <span className="text-xs font-medium block" style={{ color: 'var(--text-primary)' }}>
        {data.label as string}
      </span>
      {!!(data.cidr) && (
        <span className="text-[11px] font-mono" style={{ color: 'var(--text-secondary)' }}>
          {data.cidr as string}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function NsgNode({ data }: NodeProps) {
  const healthStatus = (data.health as string) ?? 'green'
  const highlighted = data.highlighted as boolean
  const chatHighlighted = data.chatHighlighted as boolean

  const badgeLabels: Record<string, string> = { green: 'OK', yellow: 'WARN', red: 'BLOCK' }
  const accentVar = `var(--accent-${healthStatus})`

  return (
    <div
      className="rounded-lg p-3 relative"
      style={{
        width: 160,
        border: chatHighlighted
          ? '2px solid var(--accent-orange)'
          : highlighted
          ? '2px solid var(--accent-red)'
          : '1px solid var(--border)',
        background: 'var(--bg-surface)',
        boxShadow: chatHighlighted
          ? '0 0 0 4px color-mix(in srgb, var(--accent-orange) 20%, transparent)'
          : highlighted
          ? '0 0 0 4px color-mix(in srgb, var(--accent-red) 20%, transparent)'
          : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Shield size={14} style={{ color: 'var(--text-secondary)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      {data.ruleCount != null && (
        <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {data.ruleCount as number}{' rules'}
        </span>
      )}
      {/* Health badge */}
      <span
        className="absolute -top-1 -right-1 px-1.5 py-px rounded-full text-[10px] font-semibold uppercase tracking-wide"
        style={{
          background: `color-mix(in srgb, ${accentVar} 15%, transparent)`,
          color: accentVar,
          border: `1px solid color-mix(in srgb, ${accentVar} 30%, transparent)`,
        }}
      >
        {badgeLabels[healthStatus] ?? 'OK'}
      </span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function LBNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-3"
      style={{
        width: 180,
        border: '1px solid var(--border)',
        background: 'var(--bg-surface)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Scale size={14} style={{ color: 'var(--accent-purple)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <div className="flex items-center gap-1 mt-1">
        {!!(data.sku) && (
          <span
            className="text-[11px] px-1.5 py-px rounded-full"
            style={{
              background: 'color-mix(in srgb, var(--accent-purple) 15%, transparent)',
              color: 'var(--accent-purple)',
            }}
          >
            {data.sku as string}
          </span>
        )}
        {!!(data.publicIp) && (
          <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
            {data.publicIp as string}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function PENode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-3"
      style={{
        width: 170,
        border: '1px solid var(--border)',
        background: 'var(--bg-surface)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Lock size={14} style={{ color: 'var(--accent-purple)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      {!!(data.targetService) && (
        <span className="text-[11px] mt-1 block" style={{ color: 'var(--text-muted)' }}>
          {data.targetService as string}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function GatewayNode({ data }: NodeProps) {
  const isExpressRoute = (data.gatewayType as string) === 'ExpressRoute'
  const Icon = isExpressRoute ? Globe : Waypoints

  return (
    <div
      className="rounded-lg p-3"
      style={{
        width: 180,
        border: '1px solid var(--accent-orange)',
        background: 'color-mix(in srgb, var(--accent-orange) 5%, var(--bg-surface))',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Icon size={14} style={{ color: 'var(--accent-orange)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <span className="text-[11px] mt-1 block" style={{ color: 'var(--text-secondary)' }}>
        {data.gatewayType as string} &middot; {data.sku as string}
      </span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function VMNode({ data }: NodeProps) {
  const color = 'var(--accent-green)'
  return (
    <div
      className="rounded-lg p-3 cursor-pointer"
      style={{
        width: 180,
        border: '1px solid var(--border)',
        background: 'var(--bg-surface)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Server size={14} style={{ color }} />
        <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        {!!(data.vmSize) && (
          <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
            {data.vmSize as string}
          </span>
        )}
        {!!(data.osType) && (
          <span
            className="text-[10px] px-1 py-px rounded"
            style={{
              background: 'color-mix(in srgb, var(--accent-green) 12%, transparent)',
              color: 'var(--accent-green)',
            }}
          >
            {data.osType as string}
          </span>
        )}
      </div>
      {!!(data.privateIp) && (
        <span className="text-[10px] font-mono mt-1 block" style={{ color: 'var(--text-muted)' }}>
          {data.privateIp as string}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function VMSSNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-3 cursor-pointer"
      style={{
        width: 190,
        border: '1px solid var(--border)',
        background: 'var(--bg-surface)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Layers size={14} style={{ color: 'var(--accent-blue)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        {!!(data.sku) && (
          <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
            {data.sku as string}
          </span>
        )}
        {data.capacity != null && (
          <span
            className="text-[10px] px-1 py-px rounded"
            style={{
              background: 'color-mix(in srgb, var(--accent-blue) 12%, transparent)',
              color: 'var(--accent-blue)',
            }}
          >
            {data.capacity as number} instances
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function AKSNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-3 cursor-pointer"
      style={{
        width: 190,
        border: '1px solid var(--accent-blue)',
        background: 'color-mix(in srgb, var(--accent-blue) 4%, var(--bg-surface))',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Container size={14} style={{ color: 'var(--accent-blue)' }} />
        <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        {!!(data.kubernetesVersion) && (
          <span className="text-[11px] font-mono" style={{ color: 'var(--text-secondary)' }}>
            k8s {data.kubernetesVersion as string}
          </span>
        )}
        {data.nodeCount != null && (
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            {data.nodeCount as number} nodes
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function FirewallNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-3 cursor-pointer"
      style={{
        width: 180,
        border: '1px solid var(--accent-red)',
        background: 'color-mix(in srgb, var(--accent-red) 4%, var(--bg-surface))',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <Flame size={14} style={{ color: 'var(--accent-red)' }} />
        <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        {!!(data.skuTier) && (
          <span
            className="text-[10px] px-1 py-px rounded"
            style={{
              background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)',
              color: 'var(--accent-red)',
            }}
          >
            {data.skuTier as string}
          </span>
        )}
        {!!(data.privateIp) && (
          <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
            {data.privateIp as string}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function AppGatewayNode({ data }: NodeProps) {
  return (
    <div
      className="rounded-lg p-3 cursor-pointer"
      style={{
        width: 190,
        border: '1px solid var(--accent-purple)',
        background: 'color-mix(in srgb, var(--accent-purple) 4%, var(--bg-surface))',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2">
        <AppWindow size={14} style={{ color: 'var(--accent-purple)' }} />
        <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
          {data.label as string}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        {!!(data.sku) && (
          <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
            {data.sku as string}
          </span>
        )}
        {data.capacity != null && (
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            cap: {data.capacity as number}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

const nodeTypes = {
  vnetNode: VNetNode,
  subnetNode: SubnetNode,
  nsgNode: NsgNode,
  lbNode: LBNode,
  peNode: PENode,
  gatewayNode: GatewayNode,
  vmNode: VMNode,
  vmssNode: VMSSNode,
  aksNode: AKSNode,
  firewallNode: FirewallNode,
  appGatewayNode: AppGatewayNode,
}

// ---------------------------------------------------------------------------
// Transform Functions
// ---------------------------------------------------------------------------

function mapNodeType(apiType: string): string {
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
  return mapping[apiType] ?? 'default'
}

function transformToReactFlowNodes(apiNodes: TopologyNode[], chatHighlightedIds?: Set<string>): Node[] {
  return apiNodes.map((n) => ({
    id: n.id,
    type: mapNodeType(n.type),
    data: {
      label: n.label,
      ...n.data,
      chatHighlighted: chatHighlightedIds?.has(n.id) ?? false,
    },
    position: { x: 0, y: 0 },
    ...(n.data.parentId ? { parentId: n.data.parentId as string } : {}),
    style: chatHighlightedIds?.has(n.id)
      ? {
          outline: '2px solid var(--accent-orange)',
          outlineOffset: '2px',
          boxShadow: '0 0 0 4px color-mix(in srgb, var(--accent-orange) 20%, transparent)',
          borderRadius: '8px',
        }
      : undefined,
  }))
}

function getEdgeStyle(edgeType: string, hasIssue: boolean): Partial<Edge> {
  if (hasIssue) {
    return {
      style: { stroke: 'var(--accent-red)', strokeWidth: 2.5, strokeDasharray: '6 4' },
      animated: true,
      label: 'Asymmetric block',
      labelStyle: { fontSize: 10, fill: 'var(--accent-red)' },
    }
  }
  const styles: Record<string, Partial<Edge>> = {
    peering: { style: { stroke: 'var(--accent-blue)', strokeWidth: 2 }, animated: true },
    'peering-disconnected': {
      style: { stroke: 'var(--accent-red)', strokeWidth: 2, strokeDasharray: '5 5' },
      animated: false,
    },
    'subnet-nsg': { style: { stroke: 'var(--border)', strokeWidth: 1, strokeDasharray: '4 4' } },
    'subnet-lb': { style: { stroke: 'var(--text-muted)', strokeWidth: 1.5 } },
    'subnet-pe': { style: { stroke: 'var(--accent-purple)', strokeWidth: 1, strokeDasharray: '2 4' } },
    'subnet-gateway': { style: { stroke: 'var(--accent-orange)', strokeWidth: 1.5 } },
    'subnet-vm': { style: { stroke: 'var(--accent-green)', strokeWidth: 1, strokeDasharray: '3 3' } },
    'subnet-vmss': { style: { stroke: 'var(--accent-blue)', strokeWidth: 1, strokeDasharray: '3 3' } },
    'subnet-aks': { style: { stroke: 'var(--accent-blue)', strokeWidth: 1.5 } },
    'subnet-firewall': { style: { stroke: 'var(--accent-red)', strokeWidth: 1.5 } },
    'subnet-appgw': { style: { stroke: 'var(--accent-purple)', strokeWidth: 1.5 } },
  }
  return styles[edgeType] ?? { style: { stroke: 'var(--border)', strokeWidth: 1 } }
}

function transformToReactFlowEdges(
  apiEdges: TopologyEdge[],
  issues: Array<Record<string, unknown>>
): Edge[] {
  const issueEdgeIds = new Set(
    issues.map((i) => `${i.source_nsg_id}-${i.dest_nsg_id}`)
  )

  return apiEdges.map((e) => {
    const hasIssue = issueEdgeIds.has(`${e.source}-${e.target}`)
    const edgeStyle = getEdgeStyle(e.type, hasIssue)
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      ...edgeStyle,
    } as Edge
  })
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function NetworkTopologyTab() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [topologyData, setTopologyData] = useState<TopologyData | null>(null)

  // Drill-down state
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null)
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
  const vnetCount = useMemo(
    () => topologyData?.nodes.filter((n) => n.type === 'vnet').length ?? 0,
    [topologyData]
  )
  const nsgCount = useMemo(
    () => topologyData?.nodes.filter((n) => n.type === 'nsg').length ?? 0,
    [topologyData]
  )
  const issueCount = useMemo(
    () => topologyData?.issues.length ?? 0,
    [topologyData]
  )

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

      const rfNodes = transformToReactFlowNodes(data.nodes, highlightedNodeIds)
      const rfEdges = transformToReactFlowEdges(data.edges, data.issues)
      const layout = await computeLayout(rfNodes, rfEdges)
      setNodes(layout.nodes)
      setEdges(layout.edges)

      // If the backend returned zero nodes it may still be warming up (subscription
      // registry not yet populated).  Schedule one automatic retry after 8 seconds so
      // the map appears without the user having to click Refresh manually.
      if (data.nodes.length === 0) {
        setTimeout(() => {
          setLoading(true)
          fetch('/api/proxy/network/topology')
            .then((r) => r.json())
            .then((retryData: TopologyData) => {
              if (retryData.nodes && retryData.nodes.length > 0) {
                setTopologyData(retryData)
                const rn = transformToReactFlowNodes(retryData.nodes, new Set())
                const re = transformToReactFlowEdges(retryData.edges, retryData.issues)
                computeLayout(rn, re).then((l) => { setNodes(l.nodes); setEdges(l.edges) })
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
  }, [setNodes, setEdges])

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

      // Highlight blocking NSG and dim non-path nodes
      if (data.blocking_nsg_id) {
        setNodes((nds) =>
          nds.map((n) => ({
            ...n,
            data: {
              ...n.data,
              highlighted: n.id === data.blocking_nsg_id,
            },
            style: {
              ...n.style,
              opacity: n.id === data.blocking_nsg_id ? 1 : 0.3,
            },
          }))
        )
      } else if (data.verdict === 'allowed') {
        setEdges((eds) =>
          eds.map((e) => ({
            ...e,
            style: { ...e.style, stroke: 'var(--accent-green)', strokeWidth: 2.5 },
            animated: true,
          }))
        )
      }
    } catch (err) {
      setPathError(err instanceof Error ? err.message : 'Path check failed')
    } finally {
      setPathLoading(false)
    }
  }, [pathSource, pathDest, pathPort, pathProtocol, setNodes, setEdges])

  const handleClearPathCheck = useCallback(() => {
    setPathResult(null)
    // Restore nodes/edges from topology data
    if (topologyData) {
      const rfNodes = transformToReactFlowNodes(topologyData.nodes, highlightedNodeIds)
      const rfEdges = transformToReactFlowEdges(topologyData.edges, topologyData.issues)
      computeLayout(rfNodes, rfEdges).then((layout) => {
        setNodes(layout.nodes)
        setEdges(layout.edges)
      })
    }
  }, [topologyData, setNodes, setEdges, highlightedNodeIds])

  // Resource options for path checker selects — include VMs and subnets/NSGs/VNets
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
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            onNodeClick={(_evt, node) => {
              setSelectedNode(node)
              setSelectedEdge(null)
              setDetailOpen(true)
            }}
            onEdgeClick={(_evt, edge) => {
              setSelectedEdge(edge)
              setSelectedNode(null)
              setDetailOpen(true)
            }}
            elementsSelectable
          >
            <Controls />
            <MiniMap />
            <Background variant={BackgroundVariant.Dots} />
          </ReactFlow>
          </div>
          {chatOpen && (
            <div style={{ width: 360, flexShrink: 0 }}>
              <NetworkTopologyChatPanel
                subscriptionIds={[]}
                topologyContext={topologyContext}
                nodeIndex={nodeIndex}
                onHighlight={(ids) => {
                  setHighlightedNodeIds(ids)
                  // Update node data/style in-place — no layout recalculation
                  setNodes((nds) =>
                    nds.map((n) => ({
                      ...n,
                      data: { ...n.data, chatHighlighted: ids.has(n.id) },
                      style: ids.has(n.id)
                        ? {
                            outline: '2px solid var(--accent-orange)',
                            outlineOffset: '2px',
                            boxShadow: '0 0 0 4px color-mix(in srgb, var(--accent-orange) 20%, transparent)',
                            borderRadius: '8px',
                          }
                        : { outline: undefined, boxShadow: undefined },
                    }))
                  )
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
