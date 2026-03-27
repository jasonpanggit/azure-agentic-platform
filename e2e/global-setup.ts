/**
 * Playwright global setup — acquires auth token and creates E2E Cosmos containers.
 *
 * Runs once before all tests. Sets E2E_BEARER_TOKEN in process.env
 * for test specs to use via extraHTTPHeaders.
 */
import { FullConfig } from '@playwright/test';

async function globalSetup(config: FullConfig): Promise<void> {
  const clientId = process.env.E2E_CLIENT_ID;
  const clientSecret = process.env.E2E_CLIENT_SECRET;
  const tenantId = process.env.E2E_TENANT_ID;
  const apiAudience = process.env.E2E_API_AUDIENCE || '';

  // 1. Acquire bearer token via MSAL client credentials
  if (clientId && clientSecret && tenantId) {
    const { ConfidentialClientApplication } = await import('@azure/msal-node');
    const cca = new ConfidentialClientApplication({
      auth: {
        clientId,
        clientSecret,
        authority: `https://login.microsoftonline.com/${tenantId}`,
      },
    });

    const scopes = apiAudience
      ? [`api://${apiAudience}/.default`]
      : [`${clientId}/.default`];

    const result = await cca.acquireTokenByClientCredential({ scopes });
    if (result?.accessToken) {
      process.env.E2E_BEARER_TOKEN = result.accessToken;
      console.log('E2E global setup: Bearer token acquired');
    } else {
      console.warn('E2E global setup: Failed to acquire token — tests may fail auth');
    }
  } else {
    console.warn('E2E global setup: Missing E2E_CLIENT_ID/SECRET/TENANT — using dev-mode auth');
    process.env.E2E_BEARER_TOKEN = 'dev-token';
  }

  // 2. Create E2E Cosmos containers
  const cosmosEndpoint = process.env.E2E_COSMOS_ENDPOINT;
  if (cosmosEndpoint) {
    try {
      const { CosmosClient } = await import('@azure/cosmos');
      const { DefaultAzureCredential } = await import('@azure/identity');

      const credential = new DefaultAzureCredential();
      const cosmos = new CosmosClient({ endpoint: cosmosEndpoint, aadCredentials: credential });
      const dbName = process.env.E2E_COSMOS_DB || 'aap';
      const db = cosmos.database(dbName);

      await db.containers.createIfNotExists({
        id: 'incidents-e2e',
        partitionKey: { paths: ['/domain'] },
      });
      await db.containers.createIfNotExists({
        id: 'approvals-e2e',
        partitionKey: { paths: ['/thread_id'] },
      });
      console.log('E2E global setup: Cosmos E2E containers created');
    } catch (err) {
      console.warn('E2E global setup: Cosmos container creation failed:', err);
    }
  }
}

export default globalSetup;
