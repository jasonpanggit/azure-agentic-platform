import { NextResponse } from 'next/server';
import { DefaultAzureCredential } from '@azure/identity';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface ArmResource {
  id: string;
  name: string;
  type: string;
  location: string;
  tags?: Record<string, string>;
}

interface ArmResourceGroup {
  id: string;
  name: string;
  location: string;
  tags?: Record<string, string>;
}

export interface TopologyNode {
  id: string;
  label: string;
  kind: 'subscription' | 'resourceGroup' | 'resource';
  type?: string;        // resource type (for resource nodes)
  location?: string;
  parentId: string | null;
  resourceCount?: number; // for resourceGroup nodes
}

export interface TopologyEdge {
  source: string;
  target: string;
}

export interface TopologyData {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

/**
 * GET /api/topology?subscriptions=id1,id2
 *
 * Returns a three-tier graph: subscriptions → resource groups → resources.
 * Uses the container app's managed identity via DefaultAzureCredential.
 * Caps at 500 resource nodes total to keep the graph renderable.
 */
export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const subsParam = searchParams.get('subscriptions') || '';

  try {
    const credential = new DefaultAzureCredential();
    const tokenResponse = await credential.getToken(
      'https://management.azure.com/.default'
    );

    const headers = { Authorization: `Bearer ${tokenResponse.token}` };

    // Resolve subscription list
    let subscriptionIds: string[] = subsParam
      ? subsParam.split(',').map((s) => s.trim()).filter(Boolean)
      : [];

    if (subscriptionIds.length === 0) {
      const subRes = await fetch(
        'https://management.azure.com/subscriptions?api-version=2022-12-01',
        { headers }
      );
      if (subRes.ok) {
        const subData = await subRes.json();
        subscriptionIds = (subData.value ?? [])
          .filter((s: { state: string }) => s.state === 'Enabled')
          .map((s: { subscriptionId: string }) => s.subscriptionId);
      }
    }

    // Fetch subscription display names
    const subNames: Record<string, string> = {};
    for (const subId of subscriptionIds) {
      const res = await fetch(
        `https://management.azure.com/subscriptions/${subId}?api-version=2022-12-01`,
        { headers }
      );
      if (res.ok) {
        const data = await res.json();
        subNames[subId] = data.displayName ?? subId;
      }
    }

    const nodes: TopologyNode[] = [];
    const edges: TopologyEdge[] = [];
    let totalResources = 0;

    for (const subId of subscriptionIds.slice(0, 5)) {
      const subNodeId = `sub:${subId}`;
      nodes.push({
        id: subNodeId,
        label: subNames[subId] ?? subId,
        kind: 'subscription',
        parentId: null,
      });

      // Fetch resource groups
      const rgRes = await fetch(
        `https://management.azure.com/subscriptions/${subId}/resourcegroups?api-version=2021-04-01`,
        { headers }
      );
      if (!rgRes.ok) continue;
      const rgData = await rgRes.json();
      const resourceGroups: ArmResourceGroup[] = rgData.value ?? [];

      // Fetch all resources in this subscription
      const resourcesByRg: Record<string, ArmResource[]> = {};
      let url: string | undefined =
        `https://management.azure.com/subscriptions/${subId}/resources?api-version=2021-04-01&$top=500`;

      while (url && totalResources < 500) {
        const pageRes: Response = await fetch(url, { headers });
        if (!pageRes.ok) break;
        const data = await pageRes.json();
        for (const r of data.value ?? []) {
          const rgName = r.id.split('/resourceGroups/')[1]?.split('/')[0]?.toLowerCase();
          if (rgName) {
            if (!resourcesByRg[rgName]) resourcesByRg[rgName] = [];
            resourcesByRg[rgName].push(r);
          }
        }
        url = data.nextLink;
        totalResources += (data.value ?? []).length;
      }

      // Build resource group nodes
      for (const rg of resourceGroups) {
        const rgNodeId = `rg:${subId}:${rg.name}`;
        const rgResources = resourcesByRg[rg.name.toLowerCase()] ?? [];

        nodes.push({
          id: rgNodeId,
          label: rg.name,
          kind: 'resourceGroup',
          location: rg.location,
          parentId: subNodeId,
          resourceCount: rgResources.length,
        });
        edges.push({ source: subNodeId, target: rgNodeId });

        // Add resource nodes (cap per-RG to keep graph manageable)
        for (const resource of rgResources.slice(0, 30)) {
          const rNodeId = `res:${resource.id}`;
          nodes.push({
            id: rNodeId,
            label: resource.name,
            kind: 'resource',
            type: resource.type,
            location: resource.location,
            parentId: rgNodeId,
          });
          edges.push({ source: rgNodeId, target: rNodeId });
        }
      }
    }

    return NextResponse.json({ nodes, edges } satisfies TopologyData);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to build topology: ${message}` },
      { status: 500 }
    );
  }
}
