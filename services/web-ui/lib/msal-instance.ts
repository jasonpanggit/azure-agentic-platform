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
      // No handleRedirectPromise needed — using popup flow (not redirect).
      // Popup flow keeps sessionStorage in the parent window and avoids
      // AADSTS900144 (missing client_id) caused by sessionStorage loss on redirect in private browsing.
    }
    return msalInstance;
  })();

  return initPromise;
}
