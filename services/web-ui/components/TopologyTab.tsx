'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Spinner,
  Text,
  Badge,
  Input,
  makeStyles,
  tokens,
  Tree,
  TreeItem,
  TreeItemLayout,
  TreeOpenChangeData,
  TreeOpenChangeEvent,
} from '@fluentui/react-components';
import {
  SearchRegular,
  BuildingMultipleFilled,
  FolderRegular,
  ServerRegular,
  DatabaseRegular,
  NetworkCheckRegular,
  ShieldKeyholeRegular,
  CloudRegular,
  OrganizationRegular,
} from '@fluentui/react-icons';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    height: '100%',
  },
  toolbar: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    alignItems: 'center',
  },
  searchInput: {
    maxWidth: '320px',
    flex: 1,
  },
  summary: {
    color: tokens.colorNeutralForeground3,
  },
  treeContainer: {
    flex: 1,
    overflow: 'auto',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    padding: tokens.spacingVerticalS,
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: tokens.spacingVerticalXXL,
    gap: tokens.spacingVerticalM,
    color: tokens.colorNeutralForeground3,
  },
  errorText: {
    color: tokens.colorPaletteRedForeground1,
  },
  badgeWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalXS,
  },
});

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

interface TopologyTabProps {
  subscriptions: string[];
}

// Map resource type to an icon
function resourceIcon(type?: string) {
  const t = (type ?? '').toLowerCase();
  if (t.includes('virtualmachine') || t.includes('compute')) return <ServerRegular />;
  if (t.includes('sql') || t.includes('cosmos') || t.includes('postgres') || t.includes('database')) return <DatabaseRegular />;
  if (t.includes('network') || t.includes('vnet') || t.includes('nsg')) return <NetworkCheckRegular />;
  if (t.includes('keyvault') || t.includes('vault')) return <ShieldKeyholeRegular />;
  if (t.includes('containerapp') || t.includes('aks') || t.includes('kubernetes')) return <CloudRegular />;
  return <CloudRegular />;
}

// Short display name for resource type
function shortType(type?: string): string {
  if (!type) return '';
  const parts = type.split('/');
  return parts[parts.length - 1] ?? type;
}

export function TopologyTab({ subscriptions }: TopologyTabProps) {
  const styles = useStyles();
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
      const res = await fetch(`/api/topology?${params.toString()}`);
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

  const handleOpenChange = (_: TreeOpenChangeEvent, data: TreeOpenChangeData) => {
    setOpenItems(data.openItems as Set<string>);
  };

  // Build child lookup map
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

  const renderResourceGroup = (rg: TopologyNode) => {
    const resources = childrenOf(rg.id);
    const count = rg.resourceCount ?? resources.length;
    return (
      <TreeItem key={rg.id} itemType={resources.length > 0 ? 'branch' : 'leaf'} value={rg.id}>
        <TreeItemLayout
          iconBefore={<FolderRegular />}
          aside={
            <span className={styles.badgeWrap}>
              <Badge appearance="tint" color="subtle" size="small">{count} resources</Badge>
              {rg.location && <Badge appearance="outline" size="small">{rg.location}</Badge>}
            </span>
          }
        >
          {rg.label}
        </TreeItemLayout>
        {resources.length > 0 && (
          <Tree>
            {resources.map((r) => (
              <TreeItem key={r.id} itemType="leaf" value={r.id}>
                <TreeItemLayout
                  iconBefore={resourceIcon(r.type)}
                  aside={
                    <span className={styles.badgeWrap}>
                      <Badge appearance="tint" color="informative" size="small">
                        {shortType(r.type)}
                      </Badge>
                      {r.location && <Badge appearance="outline" size="small">{r.location}</Badge>}
                    </span>
                  }
                >
                  {r.label}
                </TreeItemLayout>
              </TreeItem>
            ))}
          </Tree>
        )}
      </TreeItem>
    );
  };

  const renderSubscription = (sub: TopologyNode) => {
    const resourceGroups = childrenOf(sub.id);
    const totalResources = nodes.filter((n) => n.kind === 'resource' && nodes.find((rg) => rg.id === n.parentId && rg.parentId === sub.id)).length;
    return (
      <TreeItem key={sub.id} itemType="branch" value={sub.id}>
        <TreeItemLayout
          iconBefore={<BuildingMultipleFilled color={tokens.colorBrandForeground1} />}
          aside={
            <span className={styles.badgeWrap}>
              <Badge appearance="tint" color="brand" size="small">{resourceGroups.length} RGs</Badge>
              <Badge appearance="tint" color="subtle" size="small">{totalResources} resources</Badge>
            </span>
          }
        >
          <Text weight="semibold">{sub.label}</Text>
        </TreeItemLayout>
        <Tree>
          {resourceGroups.map(renderResourceGroup)}
        </Tree>
      </TreeItem>
    );
  };

  const rgCount = nodes.filter((n) => n.kind === 'resourceGroup').length;
  const resourceCount = nodes.filter((n) => n.kind === 'resource').length;

  return (
    <div className={styles.root}>
      <div className={styles.toolbar}>
        <Input
          className={styles.searchInput}
          placeholder="Search resources, groups, types..."
          contentBefore={<SearchRegular />}
          value={search}
          onChange={(_, d) => setSearch(d.value)}
        />
        {!loading && (
          <Text size={200} className={styles.summary}>
            {subscriptionNodes.length} subscription{subscriptionNodes.length !== 1 ? 's' : ''} · {rgCount} resource group{rgCount !== 1 ? 's' : ''} · {resourceCount} resources
          </Text>
        )}
      </div>

      {loading && <Spinner label="Building topology..." />}

      {error && !loading && (
        <Text className={styles.errorText}>{error}</Text>
      )}

      {!loading && !error && subscriptionNodes.length === 0 && (
        <div className={styles.emptyState}>
          <OrganizationRegular style={{ fontSize: '32px' }} />
          <Text weight="semibold">No resources found</Text>
          <Text size={200}>Check subscription filter or permissions.</Text>
        </div>
      )}

      {!loading && !error && subscriptionNodes.length > 0 && (
        <div className={styles.treeContainer}>
          <Tree
            openItems={openItems}
            onOpenChange={handleOpenChange}
            aria-label="Azure resource topology"
          >
            {subscriptionNodes.map(renderSubscription)}
          </Tree>
        </div>
      )}
    </div>
  );
}
