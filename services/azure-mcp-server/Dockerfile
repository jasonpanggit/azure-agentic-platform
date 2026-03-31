# Azure MCP Server Container
#
# Architecture: azmcp (localhost:5000) + lightweight Node.js reverse proxy (0.0.0.0:8080)
#
# azmcp binds to localhost only on linux/amd64. Container Apps ingress requires a process
# listening on all interfaces. A minimal Node.js HTTP proxy bridges the two.
#
# Auth: DefaultAzureCredential (managed identity in Container Apps)

FROM node:20-slim

ARG AZURE_MCP_VERSION=2.0.0-beta.34

WORKDIR /app

# Install azmcp globally at build time + netcat for the startup wait loop
RUN npm install -g "@azure/mcp@${AZURE_MCP_VERSION}" && npm cache clean --force \
    && apt-get update -qq && apt-get install -y -qq netcat-openbsd && rm -rf /var/lib/apt/lists/*

# Write the reverse proxy script
RUN printf '%s\n' \
  "const http = require('http');" \
  "const MCP_PORT = 5000, PROXY_PORT = 8080;" \
  "http.createServer((req, res) => {" \
  "  const opts = { hostname: '127.0.0.1', port: MCP_PORT, path: req.url, method: req.method, headers: req.headers };" \
  "  const p = http.request(opts, (pr) => { res.writeHead(pr.statusCode, pr.headers); pr.pipe(res); });" \
  "  p.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });" \
  "  req.pipe(p);" \
  "}).listen(PROXY_PORT, () => console.log('MCP proxy listening on', PROXY_PORT));" \
  > /app/proxy.js

# Create non-root user
RUN groupadd -r mcp && useradd -r -g mcp -m mcp && chown -R mcp:mcp /app
USER mcp

EXPOSE 8080

# Start azmcp on localhost:5000 then the proxy on 0.0.0.0:8080
CMD ["sh", "-c", "azmcp server start --transport http --dangerously-disable-http-incoming-auth & until nc -z 127.0.0.1 5000 2>/dev/null; do sleep 1; done && node /app/proxy.js"]
