/**
 * Playwright global teardown — wipes E2E Cosmos containers.
 *
 * Runs once after all tests. Idempotent — safe to run if containers
 * don't exist or if teardown runs multiple times.
 */
import { FullConfig } from '@playwright/test';

async function globalTeardown(config: FullConfig): Promise<void> {
  const cosmosEndpoint = process.env.E2E_COSMOS_ENDPOINT;
  if (!cosmosEndpoint) {
    console.log('E2E global teardown: No COSMOS_ENDPOINT — skipping cleanup');
    return;
  }

  try {
    const { CosmosClient } = await import('@azure/cosmos');
    const { DefaultAzureCredential } = await import('@azure/identity');

    const credential = new DefaultAzureCredential();
    const cosmos = new CosmosClient({ endpoint: cosmosEndpoint, aadCredentials: credential });
    const dbName = process.env.E2E_COSMOS_DB || 'aap';
    const db = cosmos.database(dbName);

    // Delete E2E-specific containers (not production containers)
    for (const containerId of ['incidents-e2e', 'approvals-e2e']) {
      try {
        await db.container(containerId).delete();
        console.log(`E2E global teardown: Deleted container ${containerId}`);
      } catch {
        // Container may not exist — safe to ignore
      }
    }
  } catch (err) {
    console.warn('E2E global teardown: Cleanup failed:', err);
  }
}

export default globalTeardown;
