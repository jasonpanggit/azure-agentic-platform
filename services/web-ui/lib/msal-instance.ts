import { PublicClientApplication } from '@azure/msal-browser';
import { msalConfig } from './msal-config';

let msalInstance: PublicClientApplication | null = null;

export function getMsalInstance(): PublicClientApplication {
  if (!msalInstance) {
    msalInstance = new PublicClientApplication(msalConfig);
  }
  return msalInstance;
}
