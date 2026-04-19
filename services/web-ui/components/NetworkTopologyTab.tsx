'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
type CytoscapeStylesheet = cytoscape.StylesheetStyle | cytoscape.StylesheetCSS
import CytoscapeComponent from 'react-cytoscapejs'
// @ts-expect-error no types
import coseBilkent from 'cytoscape-cose-bilkent'
// @ts-expect-error no types
import nodeHtmlLabel from 'cytoscape-node-html-label'
import {
  Network,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  MessageSquare,
  Eye,
  EyeOff,
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
try {
  cytoscape.use(nodeHtmlLabel)
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
// cytoscapeStylesheet — n8n-inspired: uniform roundrect cards, colored
// top-border accent per type, clean dark backgrounds, crisp thin edges
//
// Icons are rendered as real DOM <img> elements via cytoscape-node-html-label
// (see applyNodeHtmlLabels). This keeps them in the browser's vector pipeline
// rather than the Cytoscape canvas, so they stay crisp at any zoom level.
// ---------------------------------------------------------------------------

// Per-type accent colors
const TYPE_COLOR: Record<string, string> = {
  vnet:           '#3b82f6',
  subnet:         '#64748b',
  nsg:            '#f43f5e',
  vm:             '#22c55e',
  vmss:           '#34d399',
  aks:            '#0ea5e9',
  lb:             '#a78bfa',
  appgw:          '#fb923c',
  gateway:        '#fbbf24',
  firewall:       '#ef4444',
  pe:             '#818cf8',
  publicip:       '#38bdf8',
  routetable:     '#4ade80',
  localgw:        '#fcd34d',
  natgw:          '#2dd4bf',
  firewallpolicy: '#f97316',
  external:       '#475569',
}

const NODE_W = '168px'
const NODE_H = '48px'

// ---------------------------------------------------------------------------
// Cloudcraft Canvas Light stylesheet
// Light dot-grid canvas, white node cards with colored left-border accent,
// colored edges per relationship type, high-contrast labels.
// ---------------------------------------------------------------------------

const cytoscapeStylesheet: CytoscapeStylesheet[] = [
  // ── Base node — white card with subtle shadow ──────────────────────────────
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      'font-family': 'Inter, system-ui, sans-serif',
      'font-size': '11px',
      'font-weight': '500',
      'text-valign': 'center',
      'text-halign': 'center',
      'text-wrap': 'ellipsis',
      'text-max-width': '110px',
      'text-margin-x': '14px',
      color: '#1e293b',
      'background-color': '#ffffff',
      'border-width': 1,
      'border-color': '#e2e8f0',
      shape: 'roundrectangle',
      width: NODE_W,
      height: NODE_H,
      // Simulate drop shadow via ghost/outline — Cytoscape doesn't have CSS box-shadow,
      // so we use a transparent outline as a soft visual lift cue.
      'outline-width': 0,
    },
  },
  // ── Per-type: 3px colored left-border accent (background gradient trick) ──
  // We use background-gradient to paint a sharp left accent band:
  //   stop 0 = accent color, stop at ~3px from left = accent, then white
  // Cytoscape supports background-gradient-stop-colors + background-gradient-direction
  ...Object.entries(TYPE_COLOR).map(([type, color]) => ({
    selector: `node[type="${type}"]`,
    style: {
      'border-color': color,
      'border-width': 2,
      'border-opacity': 0.8,
    } as Record<string, unknown>,
  })),
  // VNet — light blue fill, more prominent
  {
    selector: 'node[type="vnet"]',
    style: {
      'background-color': '#eff6ff',
      'border-color': '#3b82f6',
      'border-width': 2,
      color: '#1e40af',
      'font-weight': '600',
      width: '178px',
      height: '52px',
    },
  },
  // Subnet — very light, dashed border, muted text
  {
    selector: 'node[type="subnet"]',
    style: {
      'background-color': '#f8fafc',
      'border-color': '#94a3b8',
      'border-width': 1,
      'border-style': 'dashed',
      color: '#475569',
    },
  },
  // External — off-white, dashed
  {
    selector: 'node[type="external"]',
    style: {
      'background-color': '#f1f5f9',
      'border-color': '#cbd5e1',
      'border-style': 'dashed',
      color: '#64748b',
    } as Record<string, unknown>,
  },
  // ── Health overlays ───────────────────────────────────────────────────────
  { selector: 'node[health="yellow"]', style: { 'border-color': '#f59e0b', 'border-width': 2 } },
  { selector: 'node[health="red"]',    style: { 'border-color': '#ef4444', 'border-width': 2.5 } },
  // ── Selected ──────────────────────────────────────────────────────────────
  {
    selector: 'node:selected',
    style: { 'border-width': 2.5, 'border-color': '#3b82f6', color: '#1e40af' },
  },
  // ── Edges — default light gray ─────────────────────────────────────────────
  {
    selector: 'edge',
    style: {
      'curve-style': 'bezier',
      'line-color': '#cbd5e1',
      width: 1,
      'target-arrow-color': '#cbd5e1',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.6,
      opacity: 0.9,
    },
  },
  // Containment — barely visible
  { selector: 'edge[type="contains"]',
    style: { 'line-color': '#e2e8f0', 'target-arrow-shape': 'none', width: 0.5, opacity: 0.4 },
  },
  // Subnet member edges — colored dashes, no arrow
  { selector: 'edge[type="subnet-vm"]',    style: { 'line-color': '#16a34a',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-vmss"]',  style: { 'line-color': '#059669',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-nsg"]',   style: { 'line-color': '#e11d48',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.6 } },
  { selector: 'edge[type="subnet-aks"]',   style: { 'line-color': '#0284c7',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-lb"]',    style: { 'line-color': '#7c3aed',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-appgw"]', style: { 'line-color': '#ea580c',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-pe"]',    style: { 'line-color': '#6366f1',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-gateway"]',style:{ 'line-color': '#d97706',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1.5, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-firewall"]',style:{'line-color': '#dc2626',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1.5, 'target-arrow-shape': 'none', opacity: 0.7 } },
  { selector: 'edge[type="subnet-routetable"]', style: { 'line-color': '#15803d', 'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.6 } },
  { selector: 'edge[type="subnet-natgw"]', style: { 'line-color': '#0d9488',  'line-style': 'dashed', 'line-dash-pattern': [6, 3] as unknown as number, width: 1, 'target-arrow-shape': 'none', opacity: 0.7 } },
  // Traffic edges — solid with arrow
  { selector: 'edge[type="peering"]',            style: { 'line-color': '#2563eb', 'target-arrow-color': '#2563eb', width: 2, opacity: 1 } },
  { selector: 'edge[type="peering-disconnected"]',style: { 'line-color': '#dc2626', 'target-arrow-color': '#dc2626', 'line-style': 'dashed', width: 2, opacity: 0.9 } },
  { selector: 'edge[type="asymmetry"]',          style: { 'line-color': '#e11d48', 'target-arrow-color': '#e11d48', 'line-style': 'dashed', width: 2.5, opacity: 1 } },
  { selector: 'edge[type="vpn-connection"]',     style: { 'line-color': '#d97706', 'target-arrow-color': '#d97706', width: 2, opacity: 1 } },
  { selector: 'edge[type="lb-backend"]',         style: { 'line-color': '#7c3aed', 'target-arrow-color': '#7c3aed', width: 1.5, opacity: 0.85 } },
  { selector: 'edge[type="appgw-backend"]',      style: { 'line-color': '#ea580c', 'target-arrow-color': '#ea580c', 'line-style': 'dashed', width: 1.5, opacity: 0.85 } },
  { selector: 'edge[type="resource-publicip"]',  style: { 'line-color': '#0284c7', 'target-arrow-color': '#0284c7', width: 1.5, opacity: 0.85 } },
  { selector: 'edge[type="nic-nsg"]',            style: { 'line-color': '#ea580c', 'target-arrow-color': '#ea580c', 'line-style': 'dashed', width: 1, opacity: 0.75 } },
  { selector: 'edge[type="pe-target"]',          style: { 'line-color': '#6366f1', 'target-arrow-color': '#6366f1', 'line-style': 'dashed', width: 1.5, opacity: 0.85 } },
  { selector: 'edge[type="firewall-policy"]',    style: { 'line-color': '#ea580c', 'target-arrow-color': '#ea580c', width: 1.5, opacity: 0.85 } },
  { selector: 'edge[type="firewall-mgmt-subnet"]',style:{ 'line-color': '#dc2626', 'target-arrow-color': '#dc2626', 'line-style': 'dashed', width: 1, opacity: 0.75 } },
  // ── Path check states ──────────────────────────────────────────────────────
  {
    selector: 'edge.path-allowed',
    style: { 'line-color': '#16a34a', 'target-arrow-color': '#16a34a', width: 2.5, opacity: 1 },
  },
  // ── Highlight states ───────────────────────────────────────────────────────
  {
    selector: '.chat-highlighted',
    style: { 'border-color': '#f97316', 'border-width': 3, 'background-color': '#fff7ed' },
  },
  {
    selector: '.issue-highlighted',
    style: { 'border-color': '#e11d48', 'border-width': 3, 'background-color': '#fff1f2', opacity: 1 },
  },
  {
    selector: '.issue-dimmed',
    style: { opacity: 0.15 },
  },
  {
    selector: '.path-blocked',
    style: { 'border-color': '#ef4444', 'border-width': 3, 'background-color': '#fef2f2' },
  },
  {
    selector: '.dimmed',
    style: { opacity: 0.18 },
  },
  {
    selector: '.search-match',
    style: { 'border-color': '#2563eb', 'border-width': 2.5, opacity: 1 },
  },
  {
    selector: '.search-dimmed',
    style: { opacity: 0.18 },
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
    publicip: 'publicIpNode',
    routetable: 'routetableNode',
    localgw: 'localgwNode',
    natgw: 'natgwNode',
    external: 'externalNode',
  }
  return mapping[apiType] ?? apiType
}

// ---------------------------------------------------------------------------
// Legend overlay
// ---------------------------------------------------------------------------

const LEGEND_NODES: { label: string; color: string; shape: string }[] = [
  { label: 'VNet',            color: '#3b82f6', shape: 'roundrect' },
  { label: 'Subnet',          color: '#94a3b8', shape: 'roundrect' },
  { label: 'NSG',             color: '#e11d48', shape: 'hex' },
  { label: 'VM',              color: '#16a34a', shape: 'circle' },
  { label: 'VMSS',            color: '#059669', shape: 'circle' },
  { label: 'AKS',             color: '#0284c7', shape: 'rect' },
  { label: 'Load Balancer',   color: '#7c3aed', shape: 'para' },
  { label: 'App Gateway',     color: '#ea580c', shape: 'para' },
  { label: 'VPN/ER Gateway',  color: '#d97706', shape: 'diamond' },
  { label: 'Firewall',        color: '#dc2626', shape: 'oct' },
  { label: 'Private Endpoint',color: '#6366f1', shape: 'cutrect' },
  { label: 'Public IP',       color: '#0284c7', shape: 'circle' },
  { label: 'Route Table',     color: '#15803d', shape: 'rect' },
  { label: 'Local Gateway',   color: '#d97706', shape: 'diamond' },
  { label: 'NAT Gateway',     color: '#0d9488', shape: 'roundrect' },
  { label: 'External',        color: '#64748b', shape: 'circle' },
]

const LEGEND_EDGES: { label: string; color: string; dashed?: boolean }[] = [
  { label: 'VNet Peering',          color: '#2563eb' },
  { label: 'Peering Disconnected',  color: '#dc2626', dashed: true },
  { label: 'NSG Asymmetry',         color: '#e11d48', dashed: true },
  { label: 'Subnet → VM',           color: '#16a34a' },
  { label: 'NIC NSG',               color: '#ea580c', dashed: true },
  { label: 'LB Backend',            color: '#7c3aed' },
  { label: 'Route Table',           color: '#15803d' },
  { label: 'VPN Connection',        color: '#d97706' },
  { label: 'PE → Target',           color: '#6366f1', dashed: true },
  { label: 'Firewall Policy',       color: '#ea580c' },
]

function LegendOverlay() {
  const [open, setOpen] = useState(false)

  return (
    <div
      className="absolute bottom-3 left-3 z-10 flex flex-col items-start gap-1"
    >
      {open && (
        <div
          className="rounded overflow-y-auto"
          style={{
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            boxShadow: '0 4px 16px rgba(0,0,0,0.10)',
            color: '#1e293b',
            fontSize: 12,
            maxHeight: 300,
            width: 200,
            padding: '8px 10px',
          }}
        >
          <p style={{ color: '#64748b', fontSize: 11, fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Nodes</p>
          {LEGEND_NODES.map(({ label, color }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: `color-mix(in srgb, ${color} 15%, #ffffff)`, border: `2px solid ${color}`, flexShrink: 0 }} />
              <span style={{ color: '#475569' }}>{label}</span>
            </div>
          ))}
          <p style={{ color: '#64748b', fontSize: 11, fontWeight: 600, marginTop: 8, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Edges</p>
          {LEGEND_EDGES.map(({ label, color, dashed }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <svg width="18" height="10" style={{ flexShrink: 0 }}>
                <line
                  x1="0" y1="5" x2="18" y2="5"
                  stroke={color}
                  strokeWidth={dashed ? 1.5 : 2}
                  strokeDasharray={dashed ? '3 2' : undefined}
                />
              </svg>
              <span style={{ color: '#475569' }}>{label}</span>
            </div>
          ))}
        </div>
      )}
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          boxShadow: '0 1px 4px rgba(0,0,0,0.10)',
          color: '#475569',
          borderRadius: 6,
          padding: '4px 8px',
          fontSize: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          cursor: 'pointer',
        }}
      >
        {open ? <EyeOff size={12} /> : <Eye size={12} />}
        Legend
      </button>
    </div>
  )
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
  const labels: Record<string, string> = { green: 'OK', yellow: 'Overly Permissive', red: 'Asymmetry Detected' }
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

const NSG_HEALTH_EXPLANATIONS: Record<string, React.ReactNode> = {
  yellow: (
    <p className="text-xs mt-2 leading-relaxed" style={{ color: 'var(--accent-yellow)' }}>
      ⚠️ This NSG has a rule with <strong>source = * and port = *</strong> at priority &lt; 1000 — it allows traffic from any source to any port. Consider tightening the source range or restricting the port.
    </p>
  ),
  red: (
    <p className="text-xs mt-2 leading-relaxed" style={{ color: 'var(--accent-red)' }}>
      🚫 <strong>NSG Asymmetry Detected.</strong> Another NSG in your topology allows outbound traffic on a port where this NSG (or vice-versa) denies the matching inbound traffic. This causes silent packet drops — traffic appears to leave the source but never arrives at the destination. See the Issues pill above the graph for specific ports and subnet pairs affected.
    </p>
  ),
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

const MIN_PANEL_WIDTH = 320
const MAX_PANEL_WIDTH = 800
const DEFAULT_PANEL_WIDTH = 420

function NodeDetailPanel({ node, edge, open, onClose }: NodeDetailPanelProps) {
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(DEFAULT_PANEL_WIDTH)

  const onDragHandleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = panelWidth

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragging.current) return
      const delta = startX.current - ev.clientX
      const next = Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, startWidth.current + delta))
      setPanelWidth(next)
    }

    const onMouseUp = () => {
      dragging.current = false
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [panelWidth])

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
            {NSG_HEALTH_EXPLANATIONS[(d.health as string)]}
            {d.ruleCount != null && <FieldRow label="Rule Count" value={String(d.ruleCount)} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
            {Array.isArray(d.rules) && d.rules.length > 0 ? (
              <>
                <p className="text-xs font-semibold mt-4 mb-0.5" style={{ color: 'var(--text-secondary)' }}>This NSG&apos;s Rules</p>
                <p className="text-[11px] mb-2" style={{ color: 'var(--text-muted)' }}>
                  Custom rules defined on this NSG. Azure evaluates these in priority order; lower number = higher priority. Default Azure rules (65000–65500) are not shown.
                </p>
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
            {d.prefix && <FieldRow label="CIDR" value={<span className="font-mono">{d.prefix as string}</span>} />}
            <FieldRow label="NSG" value={(d.nsgId as string) || 'None'} />
            {d.routeTable && <FieldRow label="Route Table" value={d.routeTable as string} />}
          </>
        )

      case 'lbNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Load Balancer Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.sku && <FieldRow label="SKU" value={d.sku as string} />}
            {d.publicIpId
              ? <FieldRow label="Public IP" value={<span className="font-mono text-xs break-all">{d.publicIpId as string}</span>} />
              : <FieldRow label="Public IP" value="Internal" />}
          </>
        )

      case 'peNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Private Endpoint Details</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.targetResourceId && <FieldRow label="Target Resource" value={<span className="font-mono text-xs break-all">{d.targetResourceId as string}</span>} />}
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

      case 'publicIpNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Public IP Address</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.ipAddress && <FieldRow label="IP Address" value={<span className="font-mono">{d.ipAddress as string}</span>} />}
            {d.allocationMethod && <FieldRow label="Allocation" value={d.allocationMethod as string} />}
            {d.sku && <FieldRow label="SKU" value={d.sku as string} />}
          </>
        )

      case 'routetableNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Route Table</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.routeCount != null && <FieldRow label="Route Count" value={String(d.routeCount)} />}
            {d.location && <FieldRow label="Location" value={d.location as string} />}
            <FieldRow label="Resource ID" value={<span className="font-mono text-xs break-all">{node.id}</span>} />
          </>
        )

      case 'localgwNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>Local Network Gateway</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.gatewayIp && <FieldRow label="Gateway IP" value={<span className="font-mono">{d.gatewayIp as string}</span>} />}
            {d.addressPrefixes && <FieldRow label="Address Prefixes" value={d.addressPrefixes as string} />}
          </>
        )

      case 'natgwNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>NAT Gateway</p>
            <FieldRow label="Name" value={d.label as string} />
            {d.idleTimeoutMinutes != null && <FieldRow label="Idle Timeout" value={`${d.idleTimeoutMinutes} min`} />}
          </>
        )

      case 'externalNode':
        return (
          <>
            <p className="text-base font-semibold mt-4 mb-2" style={{ color: 'var(--text-primary)' }}>External Resource</p>
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
      {/* sm:max-w-none overrides sheet.tsx's sm:max-w-sm so panelWidth inline style is respected */}
      <SheetContent
        side="right"
        style={{ width: panelWidth, background: 'var(--bg-surface)', borderLeft: '1px solid var(--border)', color: 'var(--text-primary)' }}
        className="p-0 sm:max-w-none"
      >
        {/* Relative wrapper needed so the absolute drag handle is positioned inside the panel */}
        <div style={{ position: 'relative', height: '100%', display: 'flex', flexDirection: 'column' }}>
          {/* Drag handle on the left edge */}
          <div
            onMouseDown={onDragHandleMouseDown}
            style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 6, cursor: 'col-resize', zIndex: 10 }}
            className="hover:bg-blue-500/30 transition-colors"
            title="Drag to resize panel width"
          />
          <div className="px-6 py-4 overflow-y-auto flex-1">
            <SheetHeader>
              <SheetTitle style={{ color: 'var(--text-primary)' }}>{title}</SheetTitle>
            </SheetHeader>
            {node && renderNodeContent()}
            {edge && renderEdgeContent()}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

interface NetworkTopologyTabProps {
  subscriptionIds?: string[]
}

export default function NetworkTopologyTab({ subscriptionIds = [] }: NetworkTopologyTabProps) {
  const cyRef = useRef<Core | null>(null)
  const miniCanvasRef = useRef<HTMLCanvasElement>(null)
  const animFrameRef = useRef<number | null>(null)
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
  const [issuesOpen, setIssuesOpen] = useState(false)
  const [focusedIssueIndex, setFocusedIssueIndex] = useState<number | null>(null)

  // Focus a specific issue — highlight its NSGs, their subnets, and connected resources
  const focusIssue = useCallback((issue: Record<string, unknown>, index: number) => {
    const cy = cyRef.current
    if (!cy) return
    const srcNsgId = String(issue.source_nsg_id ?? '')
    const dstNsgId = String(issue.dest_nsg_id ?? '')

    // Collect relevant node IDs: the two NSGs, their subnets, and everything connected to those subnets
    const relevantIds = new Set<string>()
    relevantIds.add(srcNsgId)
    relevantIds.add(dstNsgId)

    // Find subnets linked to these NSGs via subnet-nsg edges
    cy.edges('[type="subnet-nsg"]').forEach((e) => {
      if (e.target().id() === srcNsgId || e.target().id() === dstNsgId) {
        const subnetId = e.source().id()
        relevantIds.add(subnetId)
        // Add all nodes connected to those subnets
        cy.edges().filter((edge) => edge.source().id() === subnetId || edge.target().id() === subnetId).forEach((edge) => {
          relevantIds.add(edge.source().id())
          relevantIds.add(edge.target().id())
        })
      }
    })

    // Also find edges between NSGs (asymmetry edges)
    const relevantEdgeIds = new Set<string>()
    cy.edges().forEach((e) => {
      if (relevantIds.has(e.source().id()) && relevantIds.has(e.target().id())) {
        relevantEdgeIds.add(e.id())
      }
    })

    // Apply classes
    cy.elements().removeClass('issue-highlighted issue-dimmed')
    cy.nodes().forEach((n) => {
      if (relevantIds.has(n.id())) n.addClass('issue-highlighted')
      else n.addClass('issue-dimmed')
    })
    cy.edges().forEach((e) => {
      if (relevantEdgeIds.has(e.id())) e.addClass('issue-highlighted')
      else e.addClass('issue-dimmed')
    })

    // Fit view to the highlighted nodes
    const highlighted = cy.nodes('.issue-highlighted')
    if (highlighted.length > 0) cy.fit(highlighted, 80)

    setFocusedIssueIndex(index)
    setIssuesOpen(false) // close drawer so graph is fully visible
  }, [])

  const clearIssueFocus = useCallback(() => {
    cyRef.current?.elements().removeClass('issue-highlighted issue-dimmed')
    setFocusedIssueIndex(null)
  }, [])

  // Search + filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [filterTypes, setFilterTypes] = useState<Set<string>>(new Set())

  // Summary counts — all node types
  const issueCount = useMemo(() => topologyData?.issues.length ?? 0, [topologyData])
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    topologyData?.nodes.forEach((n) => { counts[n.type] = (counts[n.type] ?? 0) + 1 })
    return counts
  }, [topologyData])

  // Display order and labels for summary pills
  const PILL_TYPES: { type: string; label: string; accent?: string }[] = [
    { type: 'vnet',     label: 'VNets' },
    { type: 'subnet',   label: 'Subnets' },
    { type: 'nsg',      label: 'NSGs' },
    { type: 'vm',       label: 'VMs' },
    { type: 'vmss',     label: 'VMSS' },
    { type: 'aks',      label: 'AKS' },
    { type: 'lb',       label: 'LBs' },
    { type: 'appgw',    label: 'App GWs' },
    { type: 'gateway',  label: 'VPN/ER GWs' },
    { type: 'firewall', label: 'Firewalls', accent: 'var(--accent-red)' },
    { type: 'pe',       label: 'Private EPs' },
  ]

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

  // Cancel animation frame on unmount
  useEffect(() => {
    return () => {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current)
      }
    }
  }, [])

  // Apply search highlighting / dimming
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('search-match search-dimmed')
    const q = searchQuery.trim().toLowerCase()
    if (q) {
      cy.nodes().forEach((node) => {
        const label = String(node.data('label') ?? '').toLowerCase()
        if (label.includes(q)) {
          node.addClass('search-match')
        } else {
          node.addClass('search-dimmed')
        }
      })
    }
  }, [searchQuery])

  // Apply type filter
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('type-filtered')
    if (filterTypes.size > 0) {
      cy.nodes().forEach((node) => {
        const t = String(node.data('type') ?? '')
        if (!filterTypes.has(t)) {
          node.addClass('type-filtered')
        }
      })
    }
  }, [filterTypes])

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
        cy.edges().addClass('path-allowed')
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
      cy.edges().removeClass('path-allowed')
    }
  }, [])

  // Resource options for path checker selects
  const resourceOptions = useMemo(
    () =>
      topologyData?.nodes
        .filter((n) => ['subnet', 'nsg', 'vnet', 'vm', 'vmss', 'aks', 'appgw', 'firewall', 'lb', 'gateway'].includes(n.type))
        .map((n) => ({ id: n.id, label: `${n.label} (${n.type.toUpperCase()})` })) ?? [],
    [topologyData]
  )

  // Minimap render helper — called via cy.on('render')
  const renderMinimap = useCallback((cy: Core) => {
    const miniCanvas = miniCanvasRef.current
    if (!miniCanvas) return
    const ctx = miniCanvas.getContext('2d')
    if (!ctx) return
    const ext = cy.extent()
    const w = 160
    const h = 120
    const scaleX = w / ((ext.x2 - ext.x1) || 1)
    const scaleY = h / ((ext.y2 - ext.y1) || 1)
    ctx.clearRect(0, 0, w, h)
    // Light bg fill
    ctx.fillStyle = '#f8fafc'
    ctx.fillRect(0, 0, w, h)
    cy.nodes().forEach((node) => {
      const pos = node.position()
      const x = (pos.x - ext.x1) * scaleX
      const y = (pos.y - ext.y1) * scaleY
      ctx.fillStyle = '#94a3b8'
      ctx.fillRect(x - 2, y - 2, 4, 4)
    })
    // Viewport rectangle
    const pan = cy.pan()
    const zoom = cy.zoom()
    const vx = (-pan.x / zoom - ext.x1) * scaleX
    const vy = (-pan.y / zoom - ext.y1) * scaleY
    const vw = (cy.width() / zoom) * scaleX
    const vh = (cy.height() / zoom) * scaleY
    ctx.strokeStyle = '#2563eb'
    ctx.lineWidth = 1
    ctx.strokeRect(vx, vy, vw, vh)
  }, [])

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
          <Sheet open={pathSheetOpen} onOpenChange={(open) => { setPathSheetOpen(open); if (open) setDetailOpen(false) }}>
            <SheetTrigger asChild>
              <Button variant="outline" size="sm">
                Path Checker
              </Button>
            </SheetTrigger>
            <SheetContent style={{ background: 'var(--bg-surface)', borderLeft: '1px solid var(--border)', color: 'var(--text-primary)' }}>
              <SheetHeader>
                <SheetTitle style={{ color: 'var(--text-primary)' }}>NSG Path Check</SheetTitle>
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
                  <>
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
                    {pathResult.steps.length === 0 && (
                      <div
                        className="flex items-start gap-2 rounded border px-3 py-2 text-xs"
                        style={{
                          background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
                          borderColor: 'color-mix(in srgb, var(--accent-blue) 30%, transparent)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        ℹ️ No NSGs found on either endpoint — the path was not evaluated. This does not confirm traffic is allowed.
                      </div>
                    )}
                  </>
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
      <div className="flex flex-wrap items-center gap-2">
        {PILL_TYPES.filter(({ type }) => (typeCounts[type] ?? 0) > 0).map(({ type, label, accent }) => {
          const isActive = filterTypes.has(type)
          return (
            <button
              key={type}
              onClick={() => {
                setFilterTypes((prev) => {
                  const next = new Set(prev)
                  if (next.has(type)) {
                    next.delete(type)
                  } else {
                    next.add(type)
                  }
                  return next
                })
              }}
              className="text-xs px-2 py-1 rounded transition-all cursor-pointer"
              style={{
                background: isActive
                  ? (accent ?? 'var(--accent-blue)')
                  : accent
                  ? `color-mix(in srgb, ${accent} 12%, transparent)`
                  : 'var(--bg-subtle)',
                color: isActive ? '#fff' : (accent ?? 'var(--text-secondary)'),
                border: isActive ? `1px solid ${accent ?? 'var(--accent-blue)'}` : '1px solid transparent',
              }}
            >
              {label}: {typeCounts[type]}
            </button>
          )
        })}
        {issueCount > 0 ? (
          <button
            onClick={() => setIssuesOpen(true)}
            className="text-xs px-2 py-1 rounded cursor-pointer transition-opacity hover:opacity-80"
            style={{
              background: 'color-mix(in srgb, var(--accent-red) 15%, transparent)',
              color: 'var(--accent-red)',
              border: '1px solid color-mix(in srgb, var(--accent-red) 25%, transparent)',
            }}
          >
            🚫 Issues: {issueCount} — click to view
          </button>
        ) : (
          <span
            className="text-xs px-2 py-1 rounded"
            style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
          >
            Issues: 0
          </span>
        )}
        {filterTypes.size > 0 && (
          <button
            onClick={() => setFilterTypes(new Set())}
            className="text-xs px-2 py-1 rounded"
            style={{ color: 'var(--text-muted)', background: 'var(--bg-subtle)' }}
          >
            ✕ Clear filter
          </button>
        )}
        <span className="text-[11px] ml-1" style={{ color: 'var(--text-muted)' }}>
          · Click any node or connection to inspect details
        </span>
      </div>

      {/* Search bar */}
      {topologyData && topologyData.nodes.length > 0 && (
        <div className="flex items-center gap-2">
          <Input
            placeholder="Search nodes by name…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="max-w-xs text-sm h-8"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="text-xs"
              style={{ color: 'var(--text-muted)' }}
            >
              ✕ Clear
            </button>
          )}
        </div>
      )}

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
          <div style={{ flex: '1 1 0', minWidth: 0, background: '#f8fafc', backgroundImage: 'radial-gradient(circle, #cbd5e1 1px, transparent 1px)', backgroundSize: '24px 24px', position: 'relative' }}>
            {/* Refreshing indicator */}
            {loading && topologyData && (
              <div
                className="absolute top-3 right-3 z-10 flex items-center gap-1.5 rounded px-2 py-1 text-xs"
                style={{ background: '#ffffff', color: '#64748b', border: '1px solid #e2e8f0', boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}
              >
                <RefreshCw size={11} className="animate-spin" />
                Refreshing…
              </div>
            )}

            {/* Minimap — top-right */}
            <canvas
              ref={miniCanvasRef}
              width={160}
              height={120}
              className="absolute top-3 z-10 rounded"
              style={{
                right: loading && topologyData ? 120 : 10,
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
                opacity: 0.95,
                cursor: 'crosshair',
              }}
              onMouseDown={(e) => {
                const cy = cyRef.current
                const canvas = miniCanvasRef.current
                if (!cy || !canvas) return

                const panTo = (clientX: number, clientY: number) => {
                  const rect = canvas.getBoundingClientRect()
                  const mx = (clientX - rect.left) * (160 / rect.width)
                  const my = (clientY - rect.top) * (120 / rect.height)
                  const ext = cy.extent()
                  const scaleX = 160 / ((ext.x2 - ext.x1) || 1)
                  const scaleY = 120 / ((ext.y2 - ext.y1) || 1)
                  // Convert minimap coords → graph-world coords
                  const wx = mx / scaleX + ext.x1
                  const wy = my / scaleY + ext.y1
                  // Pan so the clicked world point is centered in the viewport
                  const zoom = cy.zoom()
                  cy.pan({
                    x: cy.width() / 2 - wx * zoom,
                    y: cy.height() / 2 - wy * zoom,
                  })
                }

                panTo(e.clientX, e.clientY)

                const onMove = (ev: MouseEvent) => panTo(ev.clientX, ev.clientY)
                const onUp = () => {
                  document.removeEventListener('mousemove', onMove)
                  document.removeEventListener('mouseup', onUp)
                }
                document.addEventListener('mousemove', onMove)
                document.addEventListener('mouseup', onUp)
              }}
            />

            {/* Legend overlay — bottom-left */}
            <LegendOverlay />

            {/* Zoom/Fit controls — bottom-right */}
            <div className="absolute bottom-3 right-3 flex flex-col gap-1 z-10">
              <button
                onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 1.2)}
                className="flex items-center justify-center w-8 h-8 rounded text-sm font-semibold"
                style={{ background: '#ffffff', color: '#475569', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.12)' }}
                title="Zoom in"
              >+</button>
              <button
                onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 0.8)}
                className="flex items-center justify-center w-8 h-8 rounded text-sm font-semibold"
                style={{ background: '#ffffff', color: '#475569', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.12)' }}
                title="Zoom out"
              >−</button>
              <button
                onClick={() => cyRef.current?.fit(undefined, 30)}
                className="flex items-center justify-center w-8 h-8 rounded text-sm"
                style={{ background: '#ffffff', color: '#475569', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.12)' }}
                title="Fit to screen"
              >⊞</button>
            </div>
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

                // ── Azure icon overlays (DOM-rendered, stays crisp at any zoom) ─
                // cytoscape-node-html-label places a real <img> element on each
                // node via an absolutely-positioned div over the canvas. The browser
                // renders the SVG in its own vector pipeline — no canvas rasterisation,
                // so icons stay sharp no matter how far you zoom in.
                ;(cy as Core & { nodeHtmlLabel: (cfg: unknown[]) => void }).nodeHtmlLabel([{
                  query: 'node[type]',
                  // center the label container on the node, then offset the icon
                  // left via a wrapper so it sits inside the card at the left edge
                  valign: 'center',
                  halign: 'center',
                  valignBox: 'center',
                  halignBox: 'center',
                  tpl: (data: Record<string, unknown>) => {
                    const type = (data.type as string) ?? ''
                    const src = `/icons/azure/${type}.svg`
                    // The container is centered on the node. We offset it to the left
                    // so the icon lands at roughly x=8px from the node's left edge.
                    return `<div style="width:22px;height:22px;transform:translateX(-72px);pointer-events:none;display:flex;align-items:center;justify-content:center;"><img src="${src}" width="20" height="20" style="display:block;pointer-events:none;" onerror="this.style.display='none'"></div>`
                  },
                }])

                // ── Edge animation loop ──────────────────────────────────────
                // Tier 1: marching-ants on dashed membership edges (line-dash-offset)
                // Tier 2: subtle width pulse on solid traffic edges (sine wave)
                const DASHED_SELECTOR = [
                  'edge[type="subnet-vm"]', 'edge[type="subnet-vmss"]', 'edge[type="subnet-nsg"]',
                  'edge[type="subnet-aks"]', 'edge[type="subnet-lb"]', 'edge[type="subnet-appgw"]',
                  'edge[type="subnet-pe"]', 'edge[type="subnet-gateway"]', 'edge[type="subnet-firewall"]',
                  'edge[type="subnet-routetable"]', 'edge[type="subnet-natgw"]',
                ].join(', ')
                const TRAFFIC_SELECTOR = [
                  'edge[type="peering"]', 'edge[type="vpn-connection"]',
                  'edge[type="lb-backend"]', 'edge[type="resource-publicip"]', 'edge[type="firewall-policy"]',
                ].join(', ')
                let offset = 0
                let tick = 0
                const animate = () => {
                  offset = (offset + 0.4) % 20
                  tick += 0.04
                  cy.batch(() => {
                    cy.edges(DASHED_SELECTOR).style('line-dash-offset', -offset)
                    const w = 1.5 + Math.sin(tick) * 0.4
                    cy.edges(TRAFFIC_SELECTOR).style('width', w)
                  })
                  animFrameRef.current = requestAnimationFrame(animate)
                }
                animFrameRef.current = requestAnimationFrame(animate)

                // Minimap
                cy.on('render', () => renderMinimap(cy))

                cy.on('tap', 'node', (evt) => {
                  const nodeData = evt.target.data() as Record<string, unknown>
                  // Clear any issue focus so the panel renders against a clean graph
                  cy.elements().removeClass('issue-highlighted issue-dimmed')
                  setFocusedIssueIndex(null)
                  setSelectedNode({
                    id: nodeData.id as string,
                    type: toNodePanelType(nodeData.type as string),
                    data: nodeData,
                    position: { x: 0, y: 0 },
                  })
                  setSelectedEdge(null)
                  setPathSheetOpen(false)
                  setDetailOpen(true)
                })
                cy.on('tap', 'edge', (evt) => {
                  const edgeData = evt.target.data() as Record<string, unknown>
                  // Clear any issue focus so the panel renders against a clean graph
                  cy.elements().removeClass('issue-highlighted issue-dimmed')
                  setFocusedIssueIndex(null)
                  setSelectedEdge({
                    id: edgeData.id as string,
                    source: edgeData.source as string,
                    target: edgeData.target as string,
                    type: edgeData.type as string,
                    data: edgeData,
                  })
                  setSelectedNode(null)
                  setPathSheetOpen(false)
                  setDetailOpen(true)
                })
                cy.on('tap', (evt) => {
                  if (evt.target === cy) setDetailOpen(false)
                })
              }}
              style={{ width: '100%', height: '100%', background: 'transparent' }}
            />
          </div>
          {chatOpen && (
            <div style={{ width: 360, flexShrink: 0 }}>
              <NetworkTopologyChatPanel
                subscriptionIds={subscriptionIds}
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
                onClose={() => {
                  setChatOpen(false)
                  setHighlightedNodeIds(new Set())
                  cyRef.current?.nodes().removeClass('chat-highlighted')
                }}
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

      {/* Focused-issue banner — fixed bottom-center, always above everything */}
      {focusedIssueIndex !== null && topologyData?.issues[focusedIssueIndex] && (() => {
        const issue = topologyData.issues[focusedIssueIndex]
        const srcName = String(issue.source_nsg_id ?? '').split('/').pop()
        const dstName = String(issue.dest_nsg_id ?? '').split('/').pop()
        return (
          <div
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-lg px-4 py-2.5 text-xs shadow-xl"
            style={{
              background: 'color-mix(in srgb, var(--accent-red) 18%, var(--bg-surface))',
              border: '1px solid var(--accent-red)',
              color: 'var(--text-primary)',
              maxWidth: '560px',
              backdropFilter: 'blur(6px)',
            }}
          >
            <span style={{ color: 'var(--accent-red)' }}>🚫</span>
            <span className="flex-1">
              <strong>Port {String(issue.port)}/TCP blocked</strong>
              {' · '}
              <span className="font-mono">{srcName}</span>
              {' → '}
              <span className="font-mono">{dstName}</span>
            </span>
            <button
              onClick={() => setIssuesOpen(true)}
              className="shrink-0 text-[10px] px-2 py-0.5 rounded"
              style={{
                background: 'var(--bg-subtle)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border)',
              }}
            >
              All issues
            </button>
            <button
              onClick={clearIssueFocus}
              className="shrink-0 text-[10px] px-2 py-0.5 rounded"
              style={{
                background: 'color-mix(in srgb, var(--accent-red) 25%, transparent)',
                color: 'var(--accent-red)',
                border: '1px solid color-mix(in srgb, var(--accent-red) 40%, transparent)',
              }}
            >
              ✕ Clear
            </button>
          </div>
        )
      })()}

      {/* Issues drawer */}
      <Sheet open={issuesOpen} onOpenChange={setIssuesOpen}>
        <SheetContent
          side="right"
          className="w-[480px] overflow-y-auto"
          style={{ background: 'var(--bg-surface)', borderLeft: '1px solid var(--border)', color: 'var(--text-primary)' }}
        >
          <SheetHeader>
            <SheetTitle style={{ color: 'var(--text-primary)' }}>Network Issues ({issueCount})</SheetTitle>
          </SheetHeader>
          <p className="text-xs mt-2 mb-4 leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            An NSG asymmetry occurs when one subnet&apos;s NSG allows outbound traffic on a port, but the destination
            subnet&apos;s NSG has no matching inbound allow rule — causing silent packet drops. Each issue below
            identifies the two NSGs and the port affected.
          </p>
          {topologyData?.issues.length ? (
            <div className="flex flex-col gap-3">
              {topologyData.issues.map((issue, i) => {
                const srcName = String(issue.source_nsg_id ?? '').split('/').pop() ?? String(issue.source_nsg_id)
                const dstName = String(issue.dest_nsg_id ?? '').split('/').pop() ?? String(issue.dest_nsg_id)
                const isFocused = focusedIssueIndex === i
                return (
                  <div
                    key={i}
                    className="rounded p-3 text-xs"
                    style={{
                      background: isFocused
                        ? 'color-mix(in srgb, var(--accent-red) 18%, transparent)'
                        : 'color-mix(in srgb, var(--accent-red) 8%, transparent)',
                      border: isFocused
                        ? '1px solid var(--accent-red)'
                        : '1px solid color-mix(in srgb, var(--accent-red) 20%, transparent)',
                    }}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <p className="font-semibold" style={{ color: 'var(--accent-red)' }}>
                        Port {String(issue.port)}/TCP blocked
                      </p>
                      <button
                        onClick={() => isFocused ? clearIssueFocus() : focusIssue(issue, i)}
                        className="shrink-0 text-[10px] px-2 py-0.5 rounded font-medium transition-colors"
                        style={{
                          background: isFocused
                            ? 'var(--accent-red)'
                            : 'color-mix(in srgb, var(--accent-red) 20%, transparent)',
                          color: isFocused ? '#fff' : 'var(--accent-red)',
                          border: '1px solid color-mix(in srgb, var(--accent-red) 40%, transparent)',
                        }}
                      >
                        {isFocused ? '✕ Clear focus' : '🔍 Focus in graph'}
                      </button>
                    </div>
                    <p className="mb-2" style={{ color: 'var(--text-primary)' }}>
                      {String(issue.description)}
                    </p>
                    <div className="flex flex-col gap-0.5" style={{ color: 'var(--text-muted)' }}>
                      <span><strong>Source NSG:</strong> <span className="font-mono">{srcName}</span></span>
                      <span><strong>Dest NSG:</strong> <span className="font-mono">{dstName}</span></span>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No issues found.</p>
          )}
        </SheetContent>
      </Sheet>

      {/* Suppress unused variable warning for highlightedNodeIds */}
      {highlightedNodeIds.size > 0 && null}
    </div>
  )
}
