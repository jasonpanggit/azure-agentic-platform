# Azure MCP Server Container
#
# Hosts the official Azure MCP Server (@azure/mcp) as an HTTP endpoint
# for AI Foundry agent MCP tool connections.
#
# Transport: Streamable HTTP on port 8080
# Auth: DefaultAzureCredential (managed identity in Container Apps)

FROM node:20-slim

# Create non-root user
RUN groupadd -r mcp && useradd -r -g mcp -m mcp

WORKDIR /app

# Install the Azure MCP Server globally
RUN npm install -g @azure/mcp@latest && npm cache clean --force

# Azure MCP Server uses DefaultAzureCredential from @azure/identity
# which reads AZURE_CLIENT_ID etc. from environment

USER mcp

EXPOSE 8080

# Start Azure MCP Server in HTTP transport mode
CMD ["npx", "-y", "@azure/mcp@latest", "server", "start", "--transport", "http", "--port", "8080"]
