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

interface ArmResourceListResponse {
  value: ArmResource[];
  nextLink?: string;
}

/**
 * GET /api/resources?subscriptions=id1,id2&type=Microsoft.Compute/virtualMachines
 *
 * Lists Azure resources across one or more subscriptions using the container
 * app's system-assigned managed identity. Optionally filter by resource type.
 */
export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const subsParam = searchParams.get('subscriptions') || '';
  const typeFilter = searchParams.get('type') || '';

  try {
    const credential = new DefaultAzureCredential();
    const tokenResponse = await credential.getToken(
      'https://management.azure.com/.default'
    );

    // If no subscriptions specified, fetch all accessible ones first
    let subscriptionIds: string[] = subsParam
      ? subsParam.split(',').map((s) => s.trim()).filter(Boolean)
      : [];

    if (subscriptionIds.length === 0) {
      const subRes = await fetch(
        'https://management.azure.com/subscriptions?api-version=2022-12-01',
        { headers: { Authorization: `Bearer ${tokenResponse.token}` } }
      );
      if (subRes.ok) {
        const subData = await subRes.json();
        subscriptionIds = (subData.value ?? [])
          .filter((s: { state: string }) => s.state === 'Enabled')
          .map((s: { subscriptionId: string }) => s.subscriptionId);
      }
    }

    const typeQuery = typeFilter ? `&$filter=resourceType eq '${typeFilter}'` : '';
    const resources: ArmResource[] = [];

    // Fetch resources from each subscription in parallel (capped at first 200 per sub)
    await Promise.all(
      subscriptionIds.slice(0, 10).map(async (subId) => {
        let url: string | undefined =
          `https://management.azure.com/subscriptions/${subId}/resources?api-version=2021-04-01&$top=200${typeQuery}`;

        while (url) {
          const res = await fetch(url, {
            headers: { Authorization: `Bearer ${tokenResponse.token}` },
          });
          if (!res.ok) break;

          const data: ArmResourceListResponse = await res.json();
          resources.push(...(data.value ?? []));
          url = data.nextLink;

          // Cap at 200 resources per subscription to avoid oversized responses
          if (resources.length >= 200) break;
        }
      })
    );

    // Sort by type then name
    resources.sort((a, b) =>
      a.type.localeCompare(b.type) || a.name.localeCompare(b.name)
    );

    // Collect distinct resource types sorted alphabetically
    const resourceTypes = [...new Set(resources.map((r) => r.type))].sort();

    return NextResponse.json({ resources, total: resources.length, resourceTypes });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `Failed to list resources: ${message}` },
      { status: 500 }
    );
  }
}
