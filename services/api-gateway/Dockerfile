# services/api-gateway/Dockerfile
# Standalone API gateway for incident ingestion
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . ./services/api_gateway/

# Non-root user for security
RUN useradd --create-home --shell /bin/bash gatewayuser
USER gatewayuser

EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "services.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
