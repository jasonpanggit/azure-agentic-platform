import { Configuration, LogLevel } from '@azure/msal-browser';

export const msalConfig: Configuration = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_AZURE_CLIENT_ID || '',
    authority: `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_TENANT_ID || 'common'}`,
    redirectUri: process.env.NEXT_PUBLIC_REDIRECT_URI || 'http://localhost:3000/callback',
    postLogoutRedirectUri: '/',
    navigateToLoginRequestUrl: true,
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

// Standard OIDC scopes — no custom api:// scopes required for login.
// To call the API gateway with a token, acquire a token silently with
// api://<gateway-client-id>/incidents.read after login.
export const loginRequest = {
  scopes: ['openid', 'profile', 'email'],
};
