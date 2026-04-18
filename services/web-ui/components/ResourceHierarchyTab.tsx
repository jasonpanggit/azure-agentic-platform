'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Search,
  Building2,
  Folder,
  Server,
  Database,
  Network,
  ShieldCheck,
  Cloud,
  ChevronRight,
  ChevronDown,
} from 'lucide-react';

interface TopologyNode {
  id: string;
  label: string;
  kind: 'subscription' | 'resourceGroup' | 'resource';
  type?: string;
  location?: string;
  parentId: string | null;
  resourceCount?: number;
}

interface TopologyEdge {
  source: string;
  target: string;
}

interface TopologyData {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  error?: string;
}

interface ResourceHierarchyTabProps {
  subscriptions: string[];
}

// Map resource type to a lucide icon
function ResourceIcon({ type }: { type?: string }) {
  const t = (type ?? '').toLowerCase();
  if (t.includes('virtualmachine') || t.includes('compute')) return <Server className="h-3.5 w-3.5" />;
  if (t.includes('sql') || t.includes('cosmos') || t.includes('postgres') || t.includes('database')) return <Database className="h-3.5 w-3.5" />;
  if (t.includes('network') || t.includes('vnet') || t.includes('nsg')) return <Network className="h-3.5 w-3.5" />;
  if (t.includes('keyvault') || t.includes('vault')) return <ShieldCheck className="h-3.5 w-3.5" />;
  return <Cloud className="h-3.5 w-3.5" />;
}

// Short display name for resource type
function shortType(type?: string): string {
  if (!type) return '';
  const parts = type.split('/');
  return parts[parts.length - 1] ?? type;
}

function ResourceGroupNode({
  rg,
  resources,
  openItems,
  onToggle,
}: {
  rg: TopologyNode;
  resources: TopologyNode[];
  openItems: Set<string>;
  onToggle: (id: string) => void;
}) {
  const count = rg.resourceCount ?? resources.length;
  const isOpen = openItems.has(rg.id);

  return (
    <Collapsible open={isOpen} onOpenChange={() => onToggle(rg.id)}>
      <CollapsibleTrigger className="flex items-center gap-2 py-1 px-2 w-full text-sm rounded-sm hover:bg-muted text-left">
        {resources.length > 0 ? (
          isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <span className="w-3.5" />
        )}
        <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate">{rg.label}</span>
        <span className="flex items-center gap-1 shrink-0">
          <Badge variant="secondary" className="text-xs px-1.5 py-0">{count} resources</Badge>
          {rg.location && (
            <Badge variant="outline" className="text-xs px-1.5 py-0">{rg.location}</Badge>
          )}
        </span>
      </CollapsibleTrigger>
      {resources.length > 0 && (
        <CollapsibleContent>
          <div className="ml-6 border-l border-border pl-2">
            {resources.map((r) => (
              <div key={r.id} className="flex items-center gap-2 py-1 px-2 text-sm rounded-sm hover:bg-muted">
                <ResourceIcon type={r.type} />
                <span className="flex-1 truncate">{r.label}</span>
                <span className="flex items-center gap-1 shrink-0">
                  <Badge variant="secondary" className="text-xs px-1.5 py-0">{shortType(r.type)}</Badge>
                  {r.location && (
                    <Badge variant="outline" className="text-xs px-1.5 py-0">{r.location}</Badge>
                  )}
                </span>
              </div>
            ))}
          </div>
        </CollapsibleContent>
      )}
    </Collapsible>
  );
}

function SubscriptionNode({
  sub,
  resourceGroups,
  nodes,
  openItems,
  onToggle,
  childrenOf,
}: {
  sub: TopologyNode;
  resourceGroups: TopologyNode[];
  nodes: TopologyNode[];
  openItems: Set<string>;
  onToggle: (id: string) => void;
  childrenOf: (parentId: string | null) => TopologyNode[];
}) {
  const isOpen = openItems.has(sub.id);
  const totalResources = resourceGroups.reduce((sum, rg) => sum + (rg.resourceCount ?? 0), 0);

  return (
    <Collapsible open={isOpen} onOpenChange={() => onToggle(sub.id)}>
      <CollapsibleTrigger className="flex items-center gap-2 py-1.5 px-2 w-full text-sm rounded-sm hover:bg-muted text-left font-semibold">
        {isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Building2 className="h-3.5 w-3.5 shrink-0 text-primary" />
        <span className="flex-1 truncate">{sub.label}</span>
        <span className="flex items-center gap-1 shrink-0">
          <Badge className="text-xs px-1.5 py-0">{resourceGroups.length} RGs</Badge>
          <Badge variant="secondary" className="text-xs px-1.5 py-0">{totalResources} resources</Badge>
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l border-border pl-2">
          {resourceGroups.map((rg) => (
            <ResourceGroupNode
              key={rg.id}
              rg={rg}
              resources={childrenOf(rg.id)}
              openItems={openItems}
              onToggle={onToggle}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ResourceHierarchyTab({ subscriptions }: ResourceHierarchyTabProps) {
  const [nodes, setNodes] = useState<TopologyNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [openItems, setOpenItems] = useState<Set<string>>(new Set());

  const loadTopology = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (subscriptions.length > 0) {
        params.set('subscriptions', subscriptions.join(','));
      }
      const res = await fetch(`/api/proxy/topology?${params.toString()}`);
      const data: TopologyData = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setNodes(data.nodes ?? []);
        // Auto-expand subscriptions and resource groups by default
        const autoOpen = new Set<string>(
          (data.nodes ?? [])
            .filter((n) => n.kind === 'subscription' || n.kind === 'resourceGroup')
            .map((n) => n.id)
        );
        setOpenItems(autoOpen);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load topology');
    } finally {
      setLoading(false);
    }
  }, [subscriptions]);

  useEffect(() => {
    loadTopology();
  }, [loadTopology]);

  const handleToggle = (id: string) => {
    setOpenItems((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Build child lookup with optional search filtering
  const childrenOf = (parentId: string | null): TopologyNode[] => {
    const q = search.toLowerCase();
    return nodes.filter((n) => {
      if (n.parentId !== parentId) return false;
      if (!q) return true;
      return (
        n.label.toLowerCase().includes(q) ||
        (n.type ?? '').toLowerCase().includes(q) ||
        (n.location ?? '').toLowerCase().includes(q)
      );
    });
  };

  const subscriptionNodes = childrenOf(null);
  const rgCount = nodes.filter((n) => n.kind === 'resourceGroup').length;
  const resourceCount = nodes.filter((n) => n.kind === 'resource').length;

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex gap-2 items-center">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search resources, groups, types..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {!loading && (
          <p className="text-sm text-muted-foreground">
            {subscriptionNodes.length} subscription{subscriptionNodes.length !== 1 ? 's' : ''} · {rgCount} resource group{rgCount !== 1 ? 's' : ''} · {resourceCount} resources
          </p>
        )}
      </div>

      {loading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      )}

      {error && !loading && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {!loading && !error && subscriptionNodes.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
          <Network className="h-8 w-8" />
          <p className="font-semibold text-foreground">No resources found</p>
          <p className="text-sm">Check subscription filter or permissions.</p>
        </div>
      )}

      {!loading && !error && subscriptionNodes.length > 0 && (
        <div className="flex-1 overflow-auto border border-border rounded-md p-2">
          {subscriptionNodes.map((sub) => (
            <SubscriptionNode
              key={sub.id}
              sub={sub}
              resourceGroups={childrenOf(sub.id)}
              nodes={nodes}
              openItems={openItems}
              onToggle={handleToggle}
              childrenOf={childrenOf}
            />
          ))}
        </div>
      )}
    </div>
  );
}
