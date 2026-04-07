import { Configuration, LogLevel } from '@azure/msal-browser';

// Prod values — these are non-secret app registration IDs (public client, no secret).
// Build-arg injection via ACR has proven unreliable; hardcoding ensures the bundle
// always has the correct values regardless of build pipeline configuration.
const CLIENT_ID = process.env.NEXT_PUBLIC_AZURE_CLIENT_ID || '505df1d3-3bd3-4151-ae87-6e5974b72a44';
const TENANT_ID = process.env.NEXT_PUBLIC_TENANT_ID || 'abbdca26-d233-4a1e-9d8c-c4eebbc16e50';
const REDIRECT_URI = process.env.NEXT_PUBLIC_REDIRECT_URI || 'https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/callback';

export const msalConfig: Configuration = {
  auth: {
    clientId: CLIENT_ID,
    authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    redirectUri: REDIRECT_URI,
    postLogoutRedirectUri: '/',
    navigateToLoginRequestUrl: true,
  },
  cache: {
    // sessionStorage works in private/incognito browsing; localStorage is blocked
    // in some browsers in private mode causing redirect auth state loss (AADSTS900144).
    // storeAuthStateInCookie: true is a fallback for Safari ITP and IE11.
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: true,
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
export const loginRequest = {
  scopes: ['openid', 'profile', 'email'],
};

// Scope for acquiring a token to call the API gateway.
// The gateway validates tokens issued for this scope.
export const gatewayTokenRequest = {
  scopes: [`api://${CLIENT_ID}/incidents.write`],
};
