import { Configuration, LogLevel } from '@azure/msal-browser';

export const msalConfig: Configuration = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_AZURE_CLIENT_ID || '',
    authority: `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_TENANT_ID || 'common'}`,
    redirectUri: process.env.NEXT_PUBLIC_REDIRECT_URI || 'http://localhost:3000/auth/callback',
    postLogoutRedirectUri: '/',
  },
  cache: {
    cacheLocation: 'localStorage',
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
      loggerCallback: (level, message) => {
        if (level === LogLevel.Error) {
          console.error('[MSAL]', message);
        }
      },
    },
  },
};

export const loginRequest = {
  scopes: [
    `api://${process.env.NEXT_PUBLIC_AZURE_CLIENT_ID}/incidents.read`,
    `api://${process.env.NEXT_PUBLIC_AZURE_CLIENT_ID}/approvals.write`,
    `api://${process.env.NEXT_PUBLIC_AZURE_CLIENT_ID}/chat.write`,
  ],
};
