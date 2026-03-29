# services/api-gateway/Dockerfile
# Standalone API gateway for incident ingestion
FROM python:3.12-slim

WORKDIR /app

# System dependencies + Node.js for @azure/mcp stdio subprocess
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        nodejs \
        npm \
    && npm install -g @azure/mcp@2.0.0-beta.34 \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . ./services/api_gateway/

# Non-root user for security — must be created after npm install
# so /usr/local/lib/node_modules is readable by all
RUN useradd --create-home --shell /bin/bash gatewayuser && \
    chmod -R a+r /usr/local/lib/node_modules/@azure/mcp 2>/dev/null || true
USER gatewayuser

EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "services.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
