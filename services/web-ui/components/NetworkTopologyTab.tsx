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
  const healthStatus = (data.healthStatus as string) ?? 'green'
  const highlighted = data.highlighted as boolean

  const badgeLabels: Record<string, string> = { green: 'OK', yellow: 'WARN', red: 'BLOCK' }
  const accentVar = `var(--accent-${healthStatus})`

  return (
    <div
      className="rounded-lg p-3 relative"
      style={{
        width: 160,
        border: highlighted
          ? '2px solid var(--accent-red)'
          : '1px solid var(--border)',
        background: 'var(--bg-surface)',
        boxShadow: highlighted
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

const nodeTypes = {
  vnetNode: VNetNode,
  subnetNode: SubnetNode,
  nsgNode: NsgNode,
  lbNode: LBNode,
  peNode: PENode,
  gatewayNode: GatewayNode,
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
  }
  return mapping[apiType] ?? 'default'
}

function transformToReactFlowNodes(apiNodes: TopologyNode[]): Node[] {
  return apiNodes.map((n) => ({
    id: n.id,
    type: mapNodeType(n.type),
    data: { label: n.label, ...n.data },
    position: { x: 0, y: 0 },
    ...(n.data.parentId ? { parentId: n.data.parentId as string } : {}),
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

  // Path checker state
  const [pathSheetOpen, setPathSheetOpen] = useState(false)
  const [pathSource, setPathSource] = useState('')
  const [pathDest, setPathDest] = useState('')
  const [pathPort, setPathPort] = useState('443')
  const [pathProtocol, setPathProtocol] = useState('TCP')
  const [pathResult, setPathResult] = useState<PathCheckResult | null>(null)
  const [pathLoading, setPathLoading] = useState(false)

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

      const rfNodes = transformToReactFlowNodes(data.nodes)
      const rfEdges = transformToReactFlowEdges(data.edges, data.issues)
      const layout = await computeLayout(rfNodes, rfEdges)
      setNodes(layout.nodes)
      setEdges(layout.edges)
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
    } catch {
      // path check error handled silently
    } finally {
      setPathLoading(false)
    }
  }, [pathSource, pathDest, pathPort, pathProtocol, setNodes, setEdges])

  const handleClearPathCheck = useCallback(() => {
    setPathResult(null)
    // Restore nodes/edges from topology data
    if (topologyData) {
      const rfNodes = transformToReactFlowNodes(topologyData.nodes)
      const rfEdges = transformToReactFlowEdges(topologyData.edges, topologyData.issues)
      computeLayout(rfNodes, rfEdges).then((layout) => {
        setNodes(layout.nodes)
        setEdges(layout.edges)
      })
    }
  }, [topologyData, setNodes, setEdges])

  // Resource options for path checker selects
  const resourceOptions = useMemo(
    () =>
      topologyData?.nodes
        .filter((n) => ['subnet', 'nsg', 'vnet'].includes(n.type))
        .map((n) => ({ id: n.id, label: n.label })) ?? [],
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
                    className="flex items-center gap-2 rounded border px-3 py-2 text-sm"
                    style={{
                      background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
                      borderColor: 'color-mix(in srgb, var(--accent-red) 30%, transparent)',
                      color: 'var(--accent-red)',
                    }}
                  >
                    <XCircle size={14} />
                    Traffic Blocked
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
        <div style={{ height: 'calc(100vh - 220px)', background: 'var(--bg-canvas)' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
          >
            <Controls />
            <MiniMap />
            <Background variant={BackgroundVariant.Dots} />
          </ReactFlow>
        </div>
      )}
    </div>
  )
}
