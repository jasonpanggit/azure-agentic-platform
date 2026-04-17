# scripts/seed-runbooks

Seeds the PostgreSQL runbook library that domain agents use for RAG-assisted troubleshooting. Runbooks are stored with pgvector embeddings for semantic similarity search.

## Contents

- `runbooks/` — markdown runbook files organized by domain
- `seed.py` — main seed script; embeds runbooks via Azure OpenAI and upserts into PostgreSQL + pgvector
- `validate.py` — validates runbook markdown against the schema before seeding
- `requirements.txt` — Python dependencies (`asyncpg`, `pgvector`, `azure-ai-projects`, etc.)
