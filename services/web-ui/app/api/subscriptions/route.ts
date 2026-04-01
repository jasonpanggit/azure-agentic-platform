import { NextResponse } from 'next/server';
import { DefaultAzureCredential } from '@azure/identity';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/subscriptions' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface AzureSubscription {
  subscriptionId: string;
  displayName: string;
  state: string;
}

interface ArmSubscriptionListResponse {
  value: AzureSubscription[];
  nextLink?: string;
}

/**
 * GET /api/subscriptions
 *
 * Returns all accessible Azure subscriptions using the container app's
 * system-assigned managed identity (DefaultAzureCredential).
 *
 * The web-ui managed identity needs Reader (or equivalent) on the subscriptions
 * returned — granted via the rbac module.
 */
export async function GET(): Promise<NextResponse> {
  try {
    log.info('request start');
    const credential = new DefaultAzureCredential();

    // Acquire ARM token
    const tokenResponse = await credential.getToken(
      'https://management.azure.com/.default'
    );

    const subscriptions: { id: string; name: string }[] = [];
    let url: string | undefined =
      'https://management.azure.com/subscriptions?api-version=2022-12-01';

    // Page through all subscriptions
    while (url) {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${tokenResponse.token}` },
      });

      if (!res.ok) {
        const body = await res.text();
        return NextResponse.json(
          { error: `ARM subscriptions API error: ${res.status} ${body}` },
          { status: res.status }
        );
      }

      const data: ArmSubscriptionListResponse = await res.json();

      for (const sub of data.value ?? []) {
        // Only include enabled subscriptions
        if (sub.state === 'Enabled') {
          subscriptions.push({
            id: sub.subscriptionId,
            name: sub.displayName,
          });
        }
      }

      url = data.nextLink;
    }

    // Sort alphabetically by name
    subscriptions.sort((a, b) => a.name.localeCompare(b.name));

    log.debug('request success', { count: subscriptions.length });
    return NextResponse.json({ subscriptions });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('arm error', { error: message });
    return NextResponse.json(
      { error: `Failed to list subscriptions: ${message}` },
      { status: 500 }
    );
  }
}
