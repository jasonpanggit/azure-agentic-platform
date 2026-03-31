import { PublicClientApplication } from '@azure/msal-browser';
import { msalConfig } from './msal-config';

let msalInstance: PublicClientApplication | null = null;
let initPromise: Promise<PublicClientApplication> | null = null;

export function getMsalInstance(): Promise<PublicClientApplication> {
  if (initPromise) return initPromise;

  initPromise = (async () => {
    if (!msalInstance) {
      msalInstance = new PublicClientApplication(msalConfig);
      await msalInstance.initialize();
      await msalInstance.handleRedirectPromise().catch(() => null);
    }
    return msalInstance;
  })();

  return initPromise;
}
